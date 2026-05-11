"""Font metric data for the 14 standard PDF fonts.

PDF readers are required by ISO 32000-1 to ship the 14 base fonts
(Helvetica + 3 variants, Times + 3 variants, Courier + 3 variants,
Symbol, ZapfDingbats). We don't ship font files — we only need the
advance-width tables to measure text.

Widths are in 1/1000 em units, the AFM convention. To get a glyph's
rendered width in points: ``(width / 1000) * font_size``.

Source: Adobe AFM files (public domain since the 14 base fonts are
spec-mandated). Mirror at github.com/tecnickcom/tc-font-core14-afms.

Milestone 0.0.2 ships Helvetica only. Other fonts arrive in 0.0.3
when font switches (bold/italic/code) come online.
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


# Fallback width for any character whose code isn't in the table. Picked
# to be the width of a typical lowercase letter — better to slightly
# over-wrap than to underestimate and overflow the column.
_FALLBACK_WIDTH = 500


def char_width(codepoint: int, font: str, size: float) -> float:
    """Return the width of one character, in points, at the given font size."""
    if font == "Helvetica":
        wx = HELVETICA_WIDTHS.get(codepoint, _FALLBACK_WIDTH)
    else:
        raise ValueError(f"font {font!r} not supported in milestone 0.0.2")
    return (wx / 1000.0) * size


def text_width(text: str, font: str, size: float) -> float:
    """Return the rendered width of ``text``, in points, at the given font size."""
    if font == "Helvetica":
        table = HELVETICA_WIDTHS
    else:
        raise ValueError(f"font {font!r} not supported in milestone 0.0.2")
    total = 0
    for ch in text:
        total += table.get(ord(ch), _FALLBACK_WIDTH)
    return (total / 1000.0) * size
