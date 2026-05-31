"""Emoji detection, inline-run construction, and text fallback.

Bridges the OpenType reader (:mod:`inkmd.emoji_font`) and the renderer.
Owns:

* deciding which Unicode codepoints are emoji that should render as glyphs,
* loading the bundled emoji font and resolving a codepoint *sequence*
  (single emoji, presentation selectors, ZWJ/flag/keycap/skin-tone
  ligatures) to a glyph image,
* splitting a text string into a mix of ordinary text runs and emoji runs,
* the **fallback** for emoji that can't render as a glyph (no font in the
  install, or — in principle — a glyph the font lacks): either a short
  textual name (``[rocket]``, the default) or dropping it entirely.
"""

from __future__ import annotations

import contextvars
import os
import unicodedata
from functools import lru_cache

from inkmd.emoji_font import EmojiFont, EmojiFontError
from inkmd.image_loader import ImageData
from inkmd.layout import EmojiImage, Run


#: Valid values for the ``emoji_fallback`` setting.
EMOJI_FALLBACK_MODES = ("name", "drop")
DEFAULT_EMOJI_FALLBACK = "name"

#: Per-compile fallback policy. A ContextVar (not a parameter threaded
#: through every recursive _render_inline call, nor module-global mutable
#: state) so the setting is scoped to one compile and safe under threads /
#: async without touching the inline-render signatures.
_fallback_mode: contextvars.ContextVar[str] = contextvars.ContextVar(
    "inkmd_emoji_fallback", default=DEFAULT_EMOJI_FALLBACK
)


def set_fallback_mode(mode: str):
    """Set the emoji fallback policy for the current context, returning the
    token to reset it. ``compile`` brackets a render with this so the
    setting is scoped to that single compile."""
    if mode not in EMOJI_FALLBACK_MODES:
        raise ValueError(
            f"emoji_fallback must be one of {EMOJI_FALLBACK_MODES}, got {mode!r}"
        )
    return _fallback_mode.set(mode)


def reset_fallback_mode(token) -> None:
    """Reset the fallback policy using a token from :func:`set_fallback_mode`."""
    _fallback_mode.reset(token)

#: Short, friendly names for emoji whose official Unicode name is long or
#: awkward. Anything not here falls back to a slugified ``unicodedata.name``.
_FALLBACK_NAME_OVERRIDES = {
    0x1F600: "grinning", 0x1F602: "joy", 0x1F642: "slight_smile",
    0x1F44D: "+1", 0x1F44E: "-1", 0x2764: "heart", 0x1F525: "fire",
    0x2705: "check", 0x274C: "x", 0x26A0: "warning", 0x2B50: "star",
    0x1F680: "rocket", 0x1F389: "tada", 0x1F4A1: "bulb", 0x1F4E6: "package",
    0x1F44F: "clap", 0x1F64F: "pray", 0x1F4DD: "memo", 0x2728: "sparkles",
    0x1F4AF: "100", 0x1F914: "thinking", 0x1F389: "tada",
}


# U+FE0F / U+FE0E: emoji / text presentation variation selectors. A FE0F
# after a base codepoint requests the colour-emoji glyph.
_VS16 = 0xFE0F
_VS15 = 0xFE0E
_ZWJ = 0x200D            # zero-width joiner (family/role ZWJ sequences)
_KEYCAP = 0x20E3         # combining enclosing keycap (#️⃣, 1️⃣ …)
_SKIN_TONES = range(0x1F3FB, 0x1F3FF + 1)  # Fitzpatrick modifiers
_TAG_RANGE = range(0xE0020, 0xE007F + 1)   # tag chars (subdivision flags)
_REGIONAL = range(0x1F1E6, 0x1F1FF + 1)    # regional indicators (flag halves)
# Codepoints in these BMP blocks are emoji-range but Unicode defaults them
# to *text* presentation: plain arrows (→ ← ↑ ↓), many misc-technical and
# misc-symbol characters. They only become emoji with an explicit FE0F or
# when the font actually carries a colour glyph. When neither holds we must
# leave them as text (→ the WinAnsi path) rather than emit an emoji-name
# label, which would be misleading for what is really a text symbol.
def _is_text_default_symbol(cp: int) -> bool:
    return (
        0x2190 <= cp <= 0x21FF   # arrows
        or 0x2300 <= cp <= 0x23FF  # misc technical (most are text-default)
        or 0x2B00 <= cp <= 0x2BFF  # misc symbols & arrows
        or cp in (0x203C, 0x2049, 0x2122, 0x2139)  # ‼ ⁉ ™ ℹ
    )


# Keycap emoji (#️⃣ *️⃣ 0️⃣–9️⃣) are an ASCII base + optional FE0F + U+20E3.
# The base is ordinary text everywhere else, so a keycap is only detected
# by looking ahead for the enclosing-keycap combiner — never by the base
# codepoint alone.
_KEYCAP_BASES = frozenset({0x23, 0x2A} | set(range(0x30, 0x3A)))


def _is_cluster_glue(cp: int) -> bool:
    """Codepoints that bind to a preceding emoji to form one cluster but
    are never standalone glyphs: ZWJ, variation selectors, the keycap
    combiner, skin-tone modifiers, and flag tag characters."""
    return (
        cp in (_ZWJ, _VS16, _VS15, _KEYCAP)
        or cp in _SKIN_TONES
        or cp in _TAG_RANGE
    )


def is_emoji_codepoint(cp: int) -> bool:
    """True if ``cp`` is a codepoint we treat as a colour-emoji glyph.

    Conservative ranges covering the common emoji blocks. Deliberately
    excludes ASCII and Latin-1 (those are text), and the variation
    selectors themselves (handled as modifiers, not standalone glyphs).
    """
    return (
        0x1F300 <= cp <= 0x1FAFF      # misc symbols/pictographs, emoji, symbols & pictographs ext
        or 0x1F000 <= cp <= 0x1F0FF   # mahjong/domino/playing cards
        or 0x2600 <= cp <= 0x27BF     # misc symbols + dingbats
        or 0x2300 <= cp <= 0x23FF     # misc technical (watch, hourglass, ⏰…)
        or 0x2B00 <= cp <= 0x2BFF     # arrows/stars (⭐, ⬆…)
        or 0x2190 <= cp <= 0x21FF     # arrows
        or cp in (0x203C, 0x2049, 0x2122, 0x2139)  # ‼ ⁉ ™ ℹ
        or 0x1F1E6 <= cp <= 0x1F1FF   # regional indicators (flags)
    )


#: Bundled color-emoji font, shipped in the pip wheel. Absent in the
#: font-less single-file zipapp build, where emoji fall back to text.
_BUNDLED_FONT = os.path.join(
    os.path.dirname(__file__), "assets", "emoji", "NotoColorEmoji.ttf"
)


def _emoji_font_path() -> str | None:
    """Path to the bundled emoji font, or None if it isn't present.

    The font ships with the pip install. It is absent in the single-file
    zipapp build, and ``INKMD_NO_EMOJI`` forces it off; in either case this
    returns None and the caller falls back to a textual representation.
    Output is reproducible: there is no system-font lookup, so a document
    renders identically wherever inkmd is installed. (A no-font pip build
    is a clean future packaging task — the font-absent path is fully
    supported and tested — but is not shipped today.)
    """
    if os.environ.get("INKMD_NO_EMOJI"):
        return None
    return _BUNDLED_FONT if os.path.isfile(_BUNDLED_FONT) else None


@lru_cache(maxsize=1)
def _load_font() -> EmojiFont | None:
    """Load and cache the emoji font, or None if unavailable/unparseable."""
    path = _emoji_font_path()
    if path is None:
        return None
    try:
        with open(path, "rb") as fh:
            return EmojiFont(fh.read())
    except (OSError, EmojiFontError):
        return None


def emoji_available() -> bool:
    """True if an emoji font is loaded and usable."""
    return _load_font() is not None


def _glyph_image(gid: int, codepoints: tuple[int, ...]):
    """Build an EmojiImage for a resolved glyph id, or None if its bitmap
    can't be extracted."""
    font = _load_font()
    if font is None:
        return None
    try:
        bmp = font.glyph_bitmap(gid)
    except EmojiFontError:
        return None
    if bmp is None:
        return None
    image = ImageData(format="png", width=bmp.width, height=bmp.height, data=bmp.png)
    aspect = bmp.width / bmp.height if bmp.height else 1.0
    return EmojiImage(
        image_id=f"emoji:{'-'.join(f'{c:04X}' for c in codepoints)}",
        image_data=image,
        aspect=aspect,
    )


def _resolve_sequence(cluster: tuple[int, ...]) -> tuple[EmojiImage | None, int]:
    """Resolve the longest emoji at the start of ``cluster``.

    Returns ``(image, consumed)`` where ``consumed`` is the number of
    leading codepoints the emoji used, or ``(None, 0)`` if the first
    codepoint can't be rendered. Tries, in order:

    1. the longest GSUB ligature whose component glyphs match a prefix of
       the cluster (with presentation selectors FE0F/FE0E dropped, as the
       font's ligatures are keyed on the non-selector glyph sequence);
    2. the base codepoint + a trailing FE0F via the cmap variation table;
    3. the bare base codepoint.
    """
    font = _load_font()
    if font is None:
        return None, 0

    # Map the cluster's codepoints to component glyphs for ligature
    # matching. Presentation selectors (FE0F/FE0E) are dropped from the key
    # — the font's ligatures are keyed on the non-selector glyph sequence —
    # but they still consume a source codepoint. ``spans[k]`` is the number
    # of source codepoints backing the first k+1 component glyphs.
    gids: list[int] = []
    spans: list[int] = []
    try:
        for i, cp in enumerate(cluster):
            if cp in (_VS16, _VS15):
                # Fold the selector into the most recent glyph's span.
                if spans:
                    spans[-1] = i + 1
                continue
            gids.append(font.glyph_id(cp))
            spans.append(i + 1)
    except EmojiFontError:
        return None, 0

    if not gids or gids[0] == 0:
        return None, 0

    # 1. Longest-match ligature over the leading gids.
    try:
        max_len = min(len(gids), font.max_ligature_length)
        for take in range(max_len, 1, -1):
            lig = font.lookup_ligature(tuple(gids[:take]))
            if lig is not None:
                used_cps = spans[take - 1]
                img = _glyph_image(lig, cluster[:used_cps])
                if img is not None:
                    return img, used_cps
    except EmojiFontError:
        pass

    # 2. base + trailing presentation selector via the variation table.
    base = cluster[0]
    if len(cluster) >= 2 and cluster[1] in (_VS16, _VS15):
        try:
            vgid = font.variation_glyph_id(base, cluster[1])
        except EmojiFontError:
            vgid = None
        if vgid:
            img = _glyph_image(vgid, cluster[:2])
            if img is not None:
                return img, 2

    # 3. the bare base codepoint — but NOT for an ASCII keycap base. A '#'
    #    or digit is only an emoji as part of a keycap ligature; if that
    #    didn't match (e.g. the keycap is absent from a subset font), it
    #    must stay ordinary text, not render as a lone glyph.
    if base in _KEYCAP_BASES:
        return None, 0
    img = _glyph_image(gids[0], (base,))
    if img is not None:
        # If a presentation selector immediately follows, swallow it so it
        # doesn't linger as stray text.
        used = 2 if (len(cluster) >= 2 and cluster[1] in (_VS16, _VS15)) else 1
        return img, used
    return None, 0


def split_text_into_runs(
    text: str,
    *,
    font: str,
    size: float,
    link_url: str | None,
    color,
    strike: bool,
    emoji_fallback: str | None = None,
) -> list[Run]:
    """Split ``text`` into ordinary text runs interleaved with emoji runs.

    Each emoji cluster the bundled font can render becomes its own emoji
    Run (an inline image); the text between emoji becomes normal text runs.

    When an emoji can't render as a glyph — there is no font (the zipapp
    build or ``INKMD_NO_EMOJI``), or the font lacks the glyph — the
    ``emoji_fallback`` policy applies:

    * ``"name"`` (default): replace it with a short ``[rocket]``-style
      label so its meaning survives;
    * ``"drop"``: omit it entirely (zero width).

    Either way the raw emoji codepoints never reach the PDF layer to be
    mangled into ``?`` by WinAnsi encoding.
    """
    if not text:
        return []
    if emoji_fallback is None:
        emoji_fallback = _fallback_mode.get()
    # Cheap fast path: text with no emoji-range codepoint AND no keycap
    # combiner has nothing to do — return one plain run without touching
    # the font (no 10MB parse). Keeps non-emoji documents as fast as before.
    if not any(is_emoji_codepoint(ord(ch)) or ord(ch) == _KEYCAP for ch in text):
        return [_text_run(text, font, size, link_url, color, strike)]

    have_font = emoji_available()
    runs: list[Run] = []
    buf: list[str] = []

    def flush_text() -> None:
        if buf:
            runs.append(_text_run("".join(buf), font, size, link_url, color, strike))
            buf.clear()

    def emit_fallback(cluster: tuple[int, ...]) -> None:
        if emoji_fallback == "drop":
            return
        # "name" (and any unknown mode) → a [label]. Append to the text
        # buffer so it joins surrounding prose as ordinary text.
        buf.append(_fallback_name(cluster))

    i = 0
    n = len(text)
    while i < n:
        cp = ord(text[i])
        if is_emoji_codepoint(cp) or _starts_keycap(text, i, n):
            # Gather the maximal emoji cluster starting here, then either
            # render it as a glyph or apply the fallback policy.
            cluster = _gather_cluster(text, i, n)
            img, used = (_resolve_sequence(cluster) if have_font else (None, 0))
            if img is not None and used > 0:
                flush_text()
                runs.append(Run(
                    text=text[i:i + used],
                    font=font, size=size, link_url=link_url,
                    color=color, strike=strike, emoji=img,
                ))
                i += used
                # A ZWJ cluster the font can't fully ligature decomposes into
                # its component emoji (e.g. man-first kiss → 👨 ❤️ 💋 👩). The
                # joiners and orphaned presentation selectors *between* those
                # components are cluster glue — never printing glyphs — but the
                # loop would otherwise re-enter on a ZWJ and append it to the
                # text buffer, where WinAnsi mangles it to a literal '?'. Skip
                # any glue that immediately trails the consumed portion so it
                # never surfaces as text. Only do this mid-cluster (used <
                # cluster length); a clean cluster boundary keeps following
                # text intact.
                if used < len(cluster):
                    while i < n and _is_cluster_glue(ord(text[i])):
                        i += 1
                continue
            # Couldn't render as a glyph. A lone text-default symbol (a
            # plain arrow, a misc-technical char) with no presentation
            # selector is really text, not an emoji — leave it for the
            # normal text path (where it renders if WinAnsi has it, else
            # '?') rather than mislabel it as an emoji name.
            if (
                len(cluster) == 1
                and _is_text_default_symbol(cluster[0])
            ):
                buf.append(text[i])
                i += 1
                continue
            # Otherwise it's a genuine emoji we can't draw: consume the
            # whole cluster and apply the fallback policy. (Consuming the
            # full cluster — not just the base — keeps a ZWJ family from
            # leaving stray component emoji behind.)
            flush_text()
            emit_fallback(cluster)
            i += len(cluster)
            continue
        buf.append(text[i])
        i += 1
    flush_text()
    return runs


def _fallback_name(codepoints: tuple[int, ...]) -> str:
    """A short ``[name]`` label for an emoji that can't render as a glyph.

    Used by the ``"name"`` fallback. Recognises a few sequence shapes that
    would otherwise produce a misleading name:

    * a regional-indicator flag pair → ``[flag:JP]`` (decoded country code);
    * a ZWJ sequence (family/role) → ``[<base>_…]`` marked as a sequence;

    otherwise names the base codepoint: a curated short name, else a slug
    of the official Unicode name, else the hex codepoint.
    """
    # Regional-indicator flag pair: the two indicators encode ISO letters.
    ri = [c for c in codepoints if c in _REGIONAL]
    if len(ri) == 2:
        code = "".join(chr(ord("A") + (c - 0x1F1E6)) for c in ri)
        return f"[flag:{code}]"

    base = next(
        (c for c in codepoints if not _is_cluster_glue(c) and c not in _REGIONAL),
        codepoints[0],
    )
    base_label = _FALLBACK_NAME_OVERRIDES.get(base)
    if base_label is None:
        try:
            name = unicodedata.name(chr(base))
            base_label = "_".join(name.lower().replace("-", " ").split())
        except (ValueError, TypeError):
            base_label = f"U+{base:04X}"

    # A ZWJ sequence is more than its base (family, couple, role…). Mark it
    # so the label doesn't masquerade as the single base emoji.
    if _ZWJ in codepoints:
        return f"[{base_label}_seq]"
    return f"[{base_label}]"


def _starts_keycap(text: str, i: int, n: int) -> bool:
    """True if a keycap emoji begins at ``i``: an ASCII keycap base
    (# * 0-9) followed by an optional FE0F and the enclosing-keycap
    combiner U+20E3. Detected by look-ahead so a bare digit or '#' stays
    ordinary text."""
    if ord(text[i]) not in _KEYCAP_BASES:
        return False
    j = i + 1
    if j < n and ord(text[j]) in (_VS16, _VS15):
        j += 1
    return j < n and ord(text[j]) == _KEYCAP


def _gather_cluster(text: str, start: int, n: int) -> tuple[int, ...]:
    """Collect the codepoints of a maximal emoji cluster from ``start``.

    A cluster is the base emoji plus any directly following glue codepoints
    (variation selectors, skin-tone modifiers, keycap combiner, tag chars)
    and ZWJ-joined continuation emoji. Resolution decides how much of the
    gathered run is actually a single glyph.
    """
    base = ord(text[start])
    cps = [base]
    # Regional-indicator flags are exactly two consecutive indicators
    # (e.g. 🇯 + 🇵 = 🇯🇵). Pull in the partner so the pair ligates.
    if base in _REGIONAL and start + 1 < n and ord(text[start + 1]) in _REGIONAL:
        cps.append(ord(text[start + 1]))
        return tuple(cps)
    j = start + 1
    while j < n:
        cp = ord(text[j])
        if _is_cluster_glue(cp):
            cps.append(cp)
            j += 1
        elif cp == _ZWJ:
            # A joiner pulls in the next emoji too (family/role sequences).
            cps.append(cp)
            j += 1
        elif cps and cps[-1] == _ZWJ and is_emoji_codepoint(cp):
            cps.append(cp)
            j += 1
        else:
            break
    return tuple(cps)


def _text_run(text, font, size, link_url, color, strike) -> Run:
    return Run(
        text=text, font=font, size=size,
        link_url=link_url, color=color, strike=strike,
    )
