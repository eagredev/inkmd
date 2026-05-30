"""Emoji detection and inline-run construction.

Bridges the OpenType reader (:mod:`inkmd.emoji_font`) and the renderer.
Owns three things:

* deciding which Unicode codepoints are emoji that should render as glyphs,
* loading the emoji font once and resolving a codepoint to a glyph image,
* splitting a text string into a mix of ordinary text runs and emoji runs.

Sequence handling (ZWJ, flags, skin tones) arrives in a later phase; this
module currently resolves single emoji codepoints (plus an optional
trailing U+FE0F presentation selector).
"""

from __future__ import annotations

import os
from functools import lru_cache

from inkmd.emoji_font import EmojiFont, EmojiFontError
from inkmd.image_loader import ImageData
from inkmd.layout import EmojiImage, Run


# U+FE0F / U+FE0E: emoji / text presentation variation selectors. A FE0F
# after a base codepoint requests the colour-emoji glyph.
_VS16 = 0xFE0F
_VS15 = 0xFE0E
_ZWJ = 0x200D            # zero-width joiner (family/role ZWJ sequences)
_KEYCAP = 0x20E3         # combining enclosing keycap (#️⃣, 1️⃣ …)
_SKIN_TONES = range(0x1F3FB, 0x1F3FF + 1)  # Fitzpatrick modifiers
_TAG_RANGE = range(0xE0020, 0xE007F + 1)   # tag chars (subdivision flags)
_REGIONAL = range(0x1F1E6, 0x1F1FF + 1)    # regional indicators (flag halves)


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


def _emoji_font_path() -> str | None:
    """Locate the emoji font: the bundled asset if present, else (during
    development, before the subset is bundled) a system Noto Color Emoji.
    Returns None if no emoji font is available — the caller then falls back
    to a textual representation.
    """
    here = os.path.dirname(__file__)
    bundled = os.path.join(here, "assets", "emoji", "emoji.ttf")
    if os.path.isfile(bundled):
        return bundled
    # Development fallback: a system Noto Color Emoji, if installed. This
    # path disappears once Phase 5 bundles the subset asset.
    import glob
    for pat in (
        "/usr/share/fonts/**/NotoColorEmoji.ttf",
        "/home/.steamos/offload/var/lib/flatpak/**/NotoColorEmoji.ttf",
        os.path.expanduser("~/.fonts/**/NotoColorEmoji.ttf"),
    ):
        hits = glob.glob(pat, recursive=True)
        if hits:
            return hits[0]
    return None


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

    # 3. the bare base codepoint.
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
) -> list[Run]:
    """Split ``text`` into ordinary text runs interleaved with emoji runs.

    Each emoji codepoint that the font can render becomes its own emoji
    Run (an inline image); the text between emoji becomes normal text
    runs. If no emoji font is available, or a codepoint isn't an emoji /
    isn't in the font, the character stays in the text run (the caller's
    fallback policy in a later phase decides what to do with unrenderable
    emoji). This keeps behaviour identical to today when emoji are absent.
    """
    if not text:
        return []
    # Cheap fast path: if the text has no emoji-range codepoint at all,
    # return a single text run WITHOUT touching the font (no glob, no
    # 10MB parse). This keeps non-emoji documents exactly as fast as
    # before. Only when an emoji codepoint is present do we load the font.
    if not any(is_emoji_codepoint(ord(ch)) for ch in text):
        return [_text_run(text, font, size, link_url, color, strike)]
    if not emoji_available():
        return [_text_run(text, font, size, link_url, color, strike)]

    runs: list[Run] = []
    buf: list[str] = []

    def flush_text() -> None:
        if buf:
            runs.append(_text_run("".join(buf), font, size, link_url, color, strike))
            buf.clear()

    i = 0
    n = len(text)
    while i < n:
        cp = ord(text[i])
        if is_emoji_codepoint(cp):
            # Gather the maximal emoji cluster starting here: the base
            # codepoint plus any following glue (selectors, skin tones,
            # keycap) and ZWJ-joined emoji. _resolve_sequence decides how
            # much of it actually forms a renderable glyph (longest-match),
            # so over-gathering is safe — unused codepoints are reconsidered.
            cluster = _gather_cluster(text, i, n)
            img, used = _resolve_sequence(cluster)
            if img is not None and used > 0:
                flush_text()
                runs.append(Run(
                    text=text[i:i + used],
                    font=font, size=size, link_url=link_url,
                    color=color, strike=strike, emoji=img,
                ))
                i += used
                continue
        buf.append(text[i])
        i += 1
    flush_text()
    return runs


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
