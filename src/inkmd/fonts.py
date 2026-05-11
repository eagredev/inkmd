"""Font metric data for the standard PDF fonts.

PDF readers are required by ISO 32000-1 to ship the 14 base fonts
(Helvetica + 3 variants, Times + 3 variants, Courier + 3 variants,
Symbol, ZapfDingbats). We don't ship font files — we only need the
advance-width tables to measure text.

Widths are in 1/1000 em units, the AFM convention. To get a glyph's
rendered width in points: ``(width / 1000) * font_size``.

Source: Adobe AFM files (public domain since the 14 base fonts are
spec-mandated). Mirror at github.com/tecnickcom/tc-font-core14-afms.

Milestone 0.0.3 ships the four faces needed for inline markdown
formatting: Helvetica (regular body), Helvetica-Bold (**bold**),
Helvetica-Oblique (*italic*), and Courier (``code``). The remaining
ten base fonts arrive when needed.

Note: Helvetica-Oblique has identical advance widths to Helvetica —
the oblique face is a slanted rendering of the same glyphs, not a
redrawn typeface. We alias accordingly to avoid duplicating the table.
"""

from __future__ import annotations


HELVETICA_WIDTHS: dict[int, int] = {
    32: 278, 33: 278, 34: 355, 35: 556, 36: 556, 37: 889, 38: 667, 39: 222,
    40: 333, 41: 333, 42: 389, 43: 584, 44: 278, 45: 333, 46: 278, 47: 278,
    48: 556, 49: 556, 50: 556, 51: 556, 52: 556, 53: 556, 54: 556, 55: 556,
    56: 556, 57: 556, 58: 278, 59: 278, 60: 584, 61: 584, 62: 584, 63: 556,
    64: 1015, 65: 667, 66: 667, 67: 722, 68: 722, 69: 667, 70: 611, 71: 778,
    72: 722, 73: 278, 74: 500, 75: 667, 76: 556, 77: 833, 78: 722, 79: 778,
    80: 667, 81: 778, 82: 722, 83: 667, 84: 611, 85: 722, 86: 667, 87: 944,
    88: 667, 89: 667, 90: 611, 91: 278, 92: 278, 93: 278, 94: 469, 95: 556,
    96: 222, 97: 556, 98: 556, 99: 500, 100: 556, 101: 556, 102: 278, 103: 556,
    104: 556, 105: 222, 106: 222, 107: 500, 108: 222, 109: 833, 110: 556, 111: 556,
    112: 556, 113: 556, 114: 333, 115: 500, 116: 278, 117: 556, 118: 500, 119: 722,
    120: 500, 121: 500, 122: 500, 123: 334, 124: 260, 125: 334, 126: 584, 161: 333,
    162: 556, 163: 556, 164: 167, 165: 556, 166: 556, 167: 556, 168: 556, 169: 191,
    170: 333, 171: 556, 172: 333, 173: 333, 174: 500, 175: 500, 177: 556, 178: 556,
    179: 556, 180: 278, 182: 537, 183: 350, 184: 222, 185: 333, 186: 333, 187: 556,
    188: 1000, 189: 1000, 191: 611, 193: 333, 194: 333, 195: 333, 196: 333, 197: 333,
    198: 333, 199: 333, 200: 333, 202: 333, 203: 333, 205: 333, 206: 333, 207: 333,
    208: 1000, 225: 1000, 227: 370, 232: 556, 233: 778, 234: 1000, 235: 365, 241: 889,
    245: 278, 248: 222, 249: 611, 250: 944, 251: 611,
}


HELVETICA_BOLD_WIDTHS: dict[int, int] = {
    32: 278, 33: 333, 34: 474, 35: 556, 36: 556, 37: 889, 38: 722, 39: 278,
    40: 333, 41: 333, 42: 389, 43: 584, 44: 278, 45: 333, 46: 278, 47: 278,
    48: 556, 49: 556, 50: 556, 51: 556, 52: 556, 53: 556, 54: 556, 55: 556,
    56: 556, 57: 556, 58: 333, 59: 333, 60: 584, 61: 584, 62: 584, 63: 611,
    64: 975, 65: 722, 66: 722, 67: 722, 68: 722, 69: 667, 70: 611, 71: 778,
    72: 722, 73: 278, 74: 556, 75: 722, 76: 611, 77: 833, 78: 722, 79: 778,
    80: 667, 81: 778, 82: 722, 83: 667, 84: 611, 85: 722, 86: 667, 87: 944,
    88: 667, 89: 667, 90: 611, 91: 333, 92: 278, 93: 333, 94: 584, 95: 556,
    96: 278, 97: 556, 98: 611, 99: 556, 100: 611, 101: 556, 102: 333, 103: 611,
    104: 611, 105: 278, 106: 278, 107: 556, 108: 278, 109: 889, 110: 611, 111: 611,
    112: 611, 113: 611, 114: 389, 115: 556, 116: 333, 117: 611, 118: 556, 119: 778,
    120: 556, 121: 556, 122: 500, 123: 389, 124: 280, 125: 389, 126: 584, 161: 333,
    162: 556, 163: 556, 164: 167, 165: 556, 166: 556, 167: 556, 168: 556, 169: 238,
    170: 500, 171: 556, 172: 333, 173: 333, 174: 611, 175: 611, 177: 556, 178: 556,
    179: 556, 180: 278, 182: 556, 183: 350, 184: 278, 185: 500, 186: 500, 187: 556,
    188: 1000, 189: 1000, 191: 611, 193: 333, 194: 333, 195: 333, 196: 333, 197: 333,
    198: 333, 199: 333, 200: 333, 202: 333, 203: 333, 205: 333, 206: 333, 207: 333,
    208: 1000, 225: 1000, 227: 370, 232: 611, 233: 778, 234: 1000, 235: 365, 241: 889,
    245: 278, 248: 278, 249: 611, 250: 944, 251: 611,
}


# Courier is monospace: every glyph in the AFM is 600 units wide. We
# still store the table to keep the lookup path uniform.
COURIER_WIDTHS: dict[int, int] = {
    32: 600, 33: 600, 34: 600, 35: 600, 36: 600, 37: 600, 38: 600, 39: 600,
    40: 600, 41: 600, 42: 600, 43: 600, 44: 600, 45: 600, 46: 600, 47: 600,
    48: 600, 49: 600, 50: 600, 51: 600, 52: 600, 53: 600, 54: 600, 55: 600,
    56: 600, 57: 600, 58: 600, 59: 600, 60: 600, 61: 600, 62: 600, 63: 600,
    64: 600, 65: 600, 66: 600, 67: 600, 68: 600, 69: 600, 70: 600, 71: 600,
    72: 600, 73: 600, 74: 600, 75: 600, 76: 600, 77: 600, 78: 600, 79: 600,
    80: 600, 81: 600, 82: 600, 83: 600, 84: 600, 85: 600, 86: 600, 87: 600,
    88: 600, 89: 600, 90: 600, 91: 600, 92: 600, 93: 600, 94: 600, 95: 600,
    96: 600, 97: 600, 98: 600, 99: 600, 100: 600, 101: 600, 102: 600, 103: 600,
    104: 600, 105: 600, 106: 600, 107: 600, 108: 600, 109: 600, 110: 600, 111: 600,
    112: 600, 113: 600, 114: 600, 115: 600, 116: 600, 117: 600, 118: 600, 119: 600,
    120: 600, 121: 600, 122: 600, 123: 600, 124: 600, 125: 600, 126: 600, 161: 600,
    162: 600, 163: 600, 164: 600, 165: 600, 166: 600, 167: 600, 168: 600, 169: 600,
    170: 600, 171: 600, 172: 600, 173: 600, 174: 600, 175: 600, 177: 600, 178: 600,
    179: 600, 180: 600, 182: 600, 183: 600, 184: 600, 185: 600, 186: 600, 187: 600,
    188: 600, 189: 600, 191: 600, 193: 600, 194: 600, 195: 600, 196: 600, 197: 600,
    198: 600, 199: 600, 200: 600, 202: 600, 203: 600, 205: 600, 206: 600, 207: 600,
    208: 600, 225: 600, 227: 600, 232: 600, 233: 600, 234: 600, 235: 600, 241: 600,
    245: 600, 248: 600, 249: 600, 250: 600, 251: 600,
}


# Helvetica-Oblique uses the same advance widths as Helvetica (the
# oblique face is a slanted rendering of the same outlines, not a
# redrawn typeface). Alias rather than duplicate.
_WIDTH_TABLES: dict[str, dict[int, int]] = {
    "Helvetica": HELVETICA_WIDTHS,
    "Helvetica-Bold": HELVETICA_BOLD_WIDTHS,
    "Helvetica-Oblique": HELVETICA_WIDTHS,
    "Courier": COURIER_WIDTHS,
}


SUPPORTED_FONTS: tuple[str, ...] = tuple(_WIDTH_TABLES)


# Fallback width for any character whose code isn't in the table. Picked
# to be the width of a typical lowercase letter — better to slightly
# over-wrap than to underestimate and overflow the column.
_FALLBACK_WIDTH = 500


def _table_for(font: str) -> dict[int, int]:
    try:
        return _WIDTH_TABLES[font]
    except KeyError:
        raise ValueError(
            f"font {font!r} not supported; available: {SUPPORTED_FONTS}"
        ) from None


def char_width(codepoint: int, font: str, size: float) -> float:
    """Return the width of one character, in points, at the given font size."""
    wx = _table_for(font).get(codepoint, _FALLBACK_WIDTH)
    return (wx / 1000.0) * size


def text_width(text: str, font: str, size: float) -> float:
    """Return the rendered width of ``text``, in points, at the given font size."""
    table = _table_for(font)
    total = 0
    for ch in text:
        total += table.get(ord(ch), _FALLBACK_WIDTH)
    return (total / 1000.0) * size
