"""Bundled embedded-font loading + the WinAnsi-boundary run split (Spine 5).

This is the INTEGRATION layer of inkmd's font-embedding path: it joins S1
(the :class:`~inkmd.truetype.TrueTypeFont` reader), S2 (measurement) and S3
(emission) to the live ``compile`` pipeline so non-Latin text renders
end-to-end instead of collapsing to ``?`` under WinAnsi.

Two responsibilities:

* **Load the embedded font.** The bundled DejaVuSans (Cyrillic / Greek /
  Latin-Extended) ships in the pip wheel under ``assets/fonts/``, loaded via
  the same ``os.path.dirname(__file__)``-relative pattern the emoji font uses
  (no system-font lookup, so output is reproducible wherever inkmd is
  installed). A caller may override it with ``font_path=`` (see
  :func:`load_embedded_font`). CJK is deferred: DejaVu has no CJK glyphs, a
  CJK codepoint maps to ``.notdef`` here, and the visible missing-glyph
  marker is a later stream (S6).

* **Split runs at the WinAnsi boundary.** :func:`split_run_for_embedding`
  walks one text run and cuts it where its codepoints cross between
  WinAnsi-representable (stay base-14) and not (route to the embedded font),
  mirroring the emoji-run split precedent. A run's every other attribute
  (size, colour, link, strike, y_shift, backgrounds, …) is preserved across
  the split; only the embedded spans gain an :class:`EmbeddedFontRef`.
"""

from __future__ import annotations

import os
import warnings
from collections import Counter
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from inkmd.fonts import is_zero_width_codepoint, to_winansi_byte
from inkmd.layout import EmbeddedFontRef, Run
from inkmd.truetype import TrueTypeFont, TrueTypeFontError


#: Bundled embedded text font, shipped in the pip wheel (mirrors the emoji
#: font layout). Absent in a font-less zipapp build, where non-WinAnsi text
#: has no embedded fallback (S6's concern).
_BUNDLED_FONT = os.path.join(
    os.path.dirname(__file__), "assets", "fonts", "DejaVuSans.ttf"
)

#: A non-`?` codepoint that ``to_winansi_byte`` collapses to ``?`` (0x3F) is
#: not representable on the base-14 WinAnsi path and routes to the embedded
#: font. ``?`` itself stays base-14 (it really is the question mark).
_QUESTION_MARK = 0x3F


class MissingGlyphWarning(UserWarning):
    """A document held codepoints no available font can draw (S6).

    Raised ONCE per :func:`inkmd.compile` call (not per codepoint) when the
    document contains >= 1 codepoint that is neither base-14-representable
    nor covered by the embedded font. Those codepoints render as visible
    ``[U+XXXX]`` markers in the PDF; this warning is the machine-readable
    companion signal so callers can detect + filter the condition
    precisely (``warnings.simplefilter("ignore", MissingGlyphWarning)``).
    Subclasses :class:`UserWarning` so it shows by default but stays
    filterable by category.
    """


def is_base14_codepoint(cp: int) -> bool:
    """True if ``cp`` renders on the base-14 WinAnsi path (not embedded).

    A codepoint is base-14-representable iff it maps to a real WinAnsi byte,
    OR it is literally ``?`` itself. Everything else (a non-``?`` codepoint
    that ``to_winansi_byte`` collapses to ``?``) is NOT representable and
    must route to the embedded font. Zero-width formatting codepoints are
    neither: both measurement paths drop them, so they cannot force a split
    on their own (see :func:`split_run_for_embedding`).
    """
    return cp == _QUESTION_MARK or to_winansi_byte(cp) != _QUESTION_MARK


def is_renderable_codepoint(cp: int, embedded_font: object | None) -> bool:
    """True iff ``cp`` can be DRAWN at all - base-14 OR an embedded glyph.

    The single unifying predicate behind S6's missing-glyph marker. A
    codepoint is drawable iff EITHER it renders on the base-14 WinAnsi path
    (:func:`is_base14_codepoint`), OR an embedded font is present and holds
    a real (non-``.notdef``) glyph for it.

    ``embedded_font`` is the parsed :class:`~inkmd.truetype.TrueTypeFont`
    (``EmbeddedFontRef.font``) or ``None`` in a font-less build / a document
    with no embedded font. When ``None``, only base-14 codepoints are
    renderable; everything else gets the marker.

    Edge guard: ``cp == 0`` (NUL) legitimately maps to ``glyph_id == 0``
    (``.notdef``), so the ``cp != 0`` clause keeps a genuine NUL from being
    falsely flagged as missing. (NUL is base-14 anyway, so this only matters
    if a font ever lacks gid 0 - the guard is belt-and-braces.)
    """
    if is_base14_codepoint(cp):
        return True
    if embedded_font is None:
        return False
    return cp != 0 and embedded_font.glyph_id(cp) != 0


def missing_glyph_marker(cp: int) -> str:
    """Render ``cp`` as the visible base-14 marker text ``[U+XXXX]``.

    Uppercase hex, no ``0x`` prefix, minimum FOUR hex digits (the Unicode
    ``U+`` convention for the BMP); astral codepoints (>= U+10000) widen
    naturally to 5 or 6 digits with NO extra zero-padding beyond that
    natural width. Every character in the result (``[ U + 0-9 A-F ]``) is
    WinAnsi-representable, so the marker itself can never recurse into the
    missing-glyph problem - it renders on the base-14 path even in a
    font-less build. THAT is why the marker is ``[U+XXXX]`` and not a
    ``.notdef`` box (needs a font) or U+FFFD (needs a glyph base-14 lacks).
    """
    return f"[U+{cp:04X}]"


#: How many distinct missing codepoints to name in the warning before
#: collapsing the rest to "(and N more)". Small so the message stays
#: readable; the marker in the PDF is the complete record.
_WARN_SAMPLE = 5


def warn_missing_glyphs(missing: list[int]) -> None:
    """Raise ONE :class:`MissingGlyphWarning` for collected missing codepoints.

    ``missing`` is the flat list of unrenderable codepoint OCCURRENCES the
    split appended (one entry per occurrence, document order). A no-op when
    the list is empty (a fully-renderable document warns nothing).

    Determinism rail: the named sample is the first :data:`_WARN_SAMPLE`
    DISTINCT codepoints in SORTED ascending order - NOT set-iteration or
    first-seen order - so the message is a pure function of the input. The
    counts (distinct, total occurrences) are likewise input-determined. The
    warning never touches the returned PDF bytes; it is the companion signal
    to the visible ``[U+XXXX]`` markers.
    """
    if not missing:
        return
    counts = Counter(missing)
    distinct = sorted(counts)  # sorted, deduplicated -> deterministic sample
    total = sum(counts.values())
    sample = distinct[:_WARN_SAMPLE]
    sample_text = ", ".join(f"U+{cp:04X}" for cp in sample)
    remaining = len(distinct) - len(sample)
    noun = "codepoint" if len(distinct) == 1 else "codepoints"
    occ = "occurrence" if total == 1 else "occurrences"
    msg = (
        f"{len(distinct)} {noun} ({total} {occ}) have no glyph in the "
        f"available font and were rendered as visible [U+XXXX] markers: "
        f"{sample_text} (and {remaining} more). Install a font pack "
        f"covering those scripts (e.g. a CJK pack) to render them."
    )
    warnings.warn(msg, MissingGlyphWarning, stacklevel=2)


def load_embedded_font(
    font_path: str | Path | None = None,
) -> tuple[TrueTypeFont, bytes] | None:
    """Load the embedded font as ``(parsed, raw_bytes)``, or None.

    With ``font_path=None`` (default), the bundled DejaVuSans is loaded, and
    None is returned only if the asset is absent (a font-less build). With an
    explicit ``font_path``, that font is loaded; a missing, unreadable, or
    unsupported font raises :class:`~inkmd.truetype.TrueTypeFontError` with a
    clear message (never a raw parse traceback leaking out of ``compile``).

    The same ``(font, font_bytes)`` pair is shared as ONE
    :class:`EmbeddedFontRef` across every embedded run in a document, so
    emission dedupes to a single Type0/FontFile2 object graph.
    """
    if font_path is None:
        return _load_bundled_font()
    path = Path(font_path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise TrueTypeFontError(
            f"could not read embedded font {str(path)!r}: {exc}"
        ) from exc
    try:
        font = TrueTypeFont(data)
        # Force the core tables to parse now so a malformed font fails here
        # with a clear error rather than mid-render.
        font.units_per_em
        font.num_glyphs
    except TrueTypeFontError as exc:
        raise TrueTypeFontError(
            f"font {str(path)!r} is not a usable glyf-flavoured TrueType "
            f"font for embedding: {exc}"
        ) from exc
    return font, data


@lru_cache(maxsize=1)
def _load_bundled_font() -> tuple[TrueTypeFont, bytes] | None:
    """Load and cache the bundled DejaVuSans, or None if it isn't present."""
    if not os.path.isfile(_BUNDLED_FONT):
        return None
    try:
        with open(_BUNDLED_FONT, "rb") as fh:
            data = fh.read()
        font = TrueTypeFont(data)
        font.units_per_em  # validate eagerly
        return font, data
    except (OSError, TrueTypeFontError):
        return None


def split_run_for_embedding(
    run: Run,
    embedded_ref: EmbeddedFontRef | None,
    missing: list[int] | None = None,
) -> list[Run]:
    """Split one text run into base-14 / embedded / missing-glyph lanes.

    Returns a list of consecutive runs whose RENDERED texts concatenate to
    ``run.text`` with every unrenderable codepoint replaced by its visible
    ``[U+XXXX]`` marker. Three lanes (this layers S6's marker split on top of
    S5's base-14/embedded split):

    * maximal base-14 spans keep the original (untagged) run;
    * maximal non-WinAnsi spans the embedded font CAN draw get
      ``embedded=embedded_ref`` so they measure + emit via that font;
    * any codepoint that is NEITHER base-14 NOR has an embedded glyph
      (:func:`is_renderable_codepoint` is False) is replaced by its
      :func:`missing_glyph_marker` text and routed onto the BASE-14 lane
      (``embedded=None``) - the marker is all base-14, so it must not carry
      the embedded ref that just failed it. Adjacent markers + base-14 text
      coalesce into one base-14 span.

    ``embedded_ref`` may be ``None`` (font-less build / no embedded font):
    then EVERY non-base-14 codepoint is unrenderable and becomes a marker.

    ``missing`` (optional) is a list the caller passes to collect every
    unrenderable codepoint occurrence (one append per occurrence, in
    document order) so ``compile`` can raise ONE deterministic warning. The
    list, not a set, is appended to here; sorting/dedup happens at the
    warning site.

    Every other attribute is preserved verbatim (``replace`` only changes
    ``text`` and ``embedded``). A run already carrying ``emoji`` or
    ``embedded`` is returned unchanged (emoji runs are images; an
    already-embedded run is not re-split). An all-base-14 run with no
    missing glyphs is returned as the single original run (identity - the
    existing all-Latin corpus stays byte-identical). Zero-width formatting
    codepoints belong to whichever span precedes them (they print nothing
    on any path), so they never start or split a span on their own.
    """
    if run.emoji is not None or run.embedded is not None:
        return [run]
    text = run.text
    if not text:
        return [run]

    embedded_font = embedded_ref.font if embedded_ref is not None else None

    # Fast path: every codepoint renders on the base-14 path -> the run is
    # untouched (identity). (No embedded span, no marker.)
    if all(
        is_base14_codepoint(ord(ch)) or is_zero_width_codepoint(ord(ch))
        for ch in text
    ):
        return [run]

    out: list[Run] = []
    buf: list[str] = []
    # None until the first non-zero-width char fixes the current span's lane.
    # True = embedded lane; False = base-14 lane (plain text OR markers).
    cur_embedded: bool | None = None

    def flush() -> None:
        if not buf:
            return
        piece = "".join(buf)
        if cur_embedded:
            out.append(replace(run, text=piece, embedded=embedded_ref))
        else:
            out.append(replace(run, text=piece))
        buf.clear()

    for ch in text:
        cp = ord(ch)
        if is_zero_width_codepoint(cp):
            # Non-printing on every path: stays with the current span rather
            # than forcing a lane decision.
            buf.append(ch)
            continue
        if is_base14_codepoint(cp):
            want_embedded = False
            piece = ch
        elif embedded_font is not None and cp != 0 and \
                embedded_font.glyph_id(cp) != 0:
            want_embedded = True
            piece = ch
        else:
            # Unrenderable: no base-14 byte and no embedded glyph. Substitute
            # the visible base-14 marker and route it onto the base-14 lane.
            if missing is not None:
                missing.append(cp)
            want_embedded = False
            piece = missing_glyph_marker(cp)
        if cur_embedded is None:
            cur_embedded = want_embedded
        elif want_embedded != cur_embedded:
            flush()
            cur_embedded = want_embedded
        buf.append(piece)
    flush()
    return out


def split_runs_for_embedding(
    runs: list[Run],
    embedded_ref: EmbeddedFontRef | None,
    missing: list[int] | None = None,
) -> list[Run]:
    """Apply :func:`split_run_for_embedding` across a list of runs."""
    out: list[Run] = []
    for run in runs:
        out.extend(split_run_for_embedding(run, embedded_ref, missing))
    return out


def document_uses_non_winansi(runs_lists) -> bool:
    """True if any run across ``runs_lists`` holds a non-WinAnsi codepoint.

    Used to decide whether a document needs the embedded font at all: a
    pure-ASCII/Latin document triggers no embedding and stays byte-identical
    to the pre-S5 output. Emoji runs are skipped (their text is the source
    emoji, rendered as an image, never via the embedded font).
    """
    for runs in runs_lists:
        for run in runs:
            if run.emoji is not None:
                continue
            for ch in run.text:
                cp = ord(ch)
                if is_zero_width_codepoint(cp):
                    continue
                if not is_base14_codepoint(cp):
                    return True
    return False
