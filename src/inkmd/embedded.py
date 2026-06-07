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
    run: Run, embedded_ref: EmbeddedFontRef
) -> list[Run]:
    """Split one text run at WinAnsi/non-WinAnsi codepoint boundaries.

    Returns a list of consecutive runs whose texts concatenate to
    ``run.text``: maximal base-14 spans keep the original (untagged) run,
    and maximal non-WinAnsi spans get ``embedded=embedded_ref`` so they
    measure + emit via the embedded font. Every other attribute is
    preserved verbatim (``replace`` only changes ``text`` and ``embedded``).

    A run already carrying ``emoji`` or ``embedded`` is returned unchanged
    (emoji runs are images; an already-embedded run is not re-split). An
    all-base-14 run is returned as the single original run (identity — the
    existing all-Latin corpus stays byte-identical). Zero-width formatting
    codepoints belong to whichever span precedes them (they print nothing
    on either path), so they never start or split a span on their own.
    """
    if run.emoji is not None or run.embedded is not None:
        return [run]
    text = run.text
    if not text:
        return [run]

    # Fast path: nothing non-WinAnsi -> the run is untouched (identity).
    if all(
        is_base14_codepoint(ord(ch)) or is_zero_width_codepoint(ord(ch))
        for ch in text
    ):
        return [run]

    out: list[Run] = []
    buf: list[str] = []
    # None until the first non-zero-width char fixes the current span's lane.
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
            # Non-printing on both paths: stays with the current span rather
            # than forcing a lane decision.
            buf.append(ch)
            continue
        want_embedded = not is_base14_codepoint(cp)
        if cur_embedded is None:
            cur_embedded = want_embedded
        elif want_embedded != cur_embedded:
            flush()
            cur_embedded = want_embedded
        buf.append(ch)
    flush()
    return out


def split_runs_for_embedding(
    runs: list[Run], embedded_ref: EmbeddedFontRef
) -> list[Run]:
    """Apply :func:`split_run_for_embedding` across a list of runs."""
    out: list[Run] = []
    for run in runs:
        out.extend(split_run_for_embedding(run, embedded_ref))
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
