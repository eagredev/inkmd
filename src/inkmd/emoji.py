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


def _resolve_glyph(codepoints: tuple[int, ...]) -> EmojiImage | None:
    """Resolve a codepoint sequence to an EmojiImage, or None if the font
    is absent or lacks the glyph. Currently handles a single base codepoint
    with an optional trailing FE0F/FE0E selector; multi-codepoint sequences
    (ZWJ, flags) are deferred to the ligature phase and return None here.
    """
    font = _load_font()
    if font is None:
        return None
    # Strip a trailing presentation selector; resolve via the variation
    # table when present, otherwise the plain cmap.
    base = codepoints[0]
    selector = codepoints[1] if len(codepoints) == 2 and codepoints[1] in (_VS16, _VS15) else None
    if len(codepoints) > (2 if selector else 1):
        return None  # genuine multi-codepoint sequence — handled later
    try:
        gid = 0
        if selector is not None:
            vgid = font.variation_glyph_id(base, selector)
            gid = vgid if vgid is not None else font.glyph_id(base)
        else:
            gid = font.glyph_id(base)
        if gid == 0:
            return None
        bmp = font.glyph_bitmap(gid)
    except EmojiFontError:
        return None
    if bmp is None:
        return None
    image = ImageData(
        format="png", width=bmp.width, height=bmp.height, data=bmp.png
    )
    aspect = bmp.width / bmp.height if bmp.height else 1.0
    return EmojiImage(
        image_id=f"emoji:{'-'.join(f'{c:04X}' for c in codepoints)}",
        image_data=image,
        aspect=aspect,
    )


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
            # Consume an optional trailing presentation selector.
            seq = [cp]
            if i + 1 < n and ord(text[i + 1]) in (_VS16, _VS15):
                seq.append(ord(text[i + 1]))
            glyph = _resolve_glyph(tuple(seq))
            if glyph is not None:
                flush_text()
                runs.append(Run(
                    text="".join(chr(c) for c in seq),
                    font=font, size=size, link_url=link_url,
                    color=color, strike=strike, emoji=glyph,
                ))
                i += len(seq)
                continue
        buf.append(text[i])
        i += 1
    flush_text()
    return runs


def _text_run(text, font, size, link_url, color, strike) -> Run:
    return Run(
        text=text, font=font, size=size,
        link_url=link_url, color=color, strike=strike,
    )
