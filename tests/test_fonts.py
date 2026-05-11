"""Font metric tests — milestone 0.0.2."""

from __future__ import annotations

import pytest

from inkmd.fonts import HELVETICA_WIDTHS, char_width, text_width


def test_helvetica_table_covers_ascii_printable():
    """Every printable ASCII codepoint (32..126) must have a width."""
    for c in range(32, 127):
        assert c in HELVETICA_WIDTHS, f"missing Helvetica width for codepoint {c}"


def test_helvetica_known_widths():
    """Spot-check a few widths against the published AFM values."""
    # From Helvetica.afm: M=833, W=944, i=222, space=278, period=278
    assert HELVETICA_WIDTHS[ord("M")] == 833
    assert HELVETICA_WIDTHS[ord("W")] == 944
    assert HELVETICA_WIDTHS[ord("i")] == 222
    assert HELVETICA_WIDTHS[ord(" ")] == 278
    assert HELVETICA_WIDTHS[ord(".")] == 278


def test_char_width_in_points():
    """At 12pt, an 'M' should be (833 / 1000) * 12 = 9.996 points wide."""
    w = char_width(ord("M"), "Helvetica", 12.0)
    assert abs(w - 9.996) < 1e-9


def test_text_width_sums_chars():
    """Width of 'Mi' must equal width('M') + width('i')."""
    w_M = char_width(ord("M"), "Helvetica", 12.0)
    w_i = char_width(ord("i"), "Helvetica", 12.0)
    w_Mi = text_width("Mi", "Helvetica", 12.0)
    assert abs(w_Mi - (w_M + w_i)) < 1e-9


def test_text_width_empty_string():
    assert text_width("", "Helvetica", 12.0) == 0


def test_text_width_scales_with_size():
    """Doubling font size doubles the rendered width."""
    w12 = text_width("Hello", "Helvetica", 12.0)
    w24 = text_width("Hello", "Helvetica", 24.0)
    assert abs(w24 - 2 * w12) < 1e-9


def test_text_width_falls_back_for_missing_glyph():
    """Codepoints outside the AFM table must still produce a finite width."""
    # U+2603 SNOWMAN is not in Helvetica's table; should fall back, not error.
    w = text_width("☃", "Helvetica", 12.0)
    assert w > 0


def test_unknown_font_raises():
    with pytest.raises(ValueError):
        text_width("hello", "NotAFont", 12.0)


# --- milestone 0.0.3: new font tables -------------------------------------


def test_supported_fonts_includes_four_faces():
    from inkmd.fonts import SUPPORTED_FONTS
    assert "Helvetica" in SUPPORTED_FONTS
    assert "Helvetica-Bold" in SUPPORTED_FONTS
    assert "Helvetica-Oblique" in SUPPORTED_FONTS
    assert "Courier" in SUPPORTED_FONTS


def test_helvetica_bold_known_widths():
    """Spot-check Helvetica-Bold against published AFM values."""
    from inkmd.fonts import HELVETICA_BOLD_WIDTHS
    # AFM: Bold M=833, exclam=333, ampersand=722
    assert HELVETICA_BOLD_WIDTHS[ord("M")] == 833
    assert HELVETICA_BOLD_WIDTHS[ord("!")] == 333
    assert HELVETICA_BOLD_WIDTHS[ord("&")] == 722


def test_courier_is_monospace():
    """Every encoded glyph in Courier has width 600."""
    from inkmd.fonts import COURIER_WIDTHS
    distinct = set(COURIER_WIDTHS.values())
    assert distinct == {600}


def test_helvetica_oblique_shares_helvetica_widths():
    """Oblique is a slanted rendering of Helvetica; widths are identical."""
    w_regular = text_width("Hello, world!", "Helvetica", 12.0)
    w_oblique = text_width("Hello, world!", "Helvetica-Oblique", 12.0)
    assert w_regular == w_oblique


def test_helvetica_bold_wider_than_regular_for_most_text():
    """A typical English sentence is wider in bold than regular."""
    text = "The quick brown fox jumps over the lazy dog"
    w_regular = text_width(text, "Helvetica", 12.0)
    w_bold = text_width(text, "Helvetica-Bold", 12.0)
    assert w_bold > w_regular


def test_courier_text_width_is_monospace_count():
    """At 12pt Courier, 10 chars = (600/1000)*12*10 = 72 points exactly."""
    w = text_width("0123456789", "Courier", 12.0)
    assert abs(w - 72.0) < 1e-9


# --- Regression: width measurement must agree with PDF rendering ----------


def test_em_dash_width_matches_rendered_glyph():
    """The em dash measures 1000 units (= 12pt at 12pt) in Helvetica.

    Regression for 0.0.3 visual bug: previously the AFM table was
    indexed by PostScript StandardEncoding, so the WinAnsi-mapped byte
    for em dash had no entry and fell back to the 500-unit default,
    measuring 6pt while the renderer drew 12pt. Letters after em dashes
    visibly overlapped.
    """
    w = text_width("—", "Helvetica", 12.0)
    assert abs(w - 12.0) < 1e-9, (
        f"em dash should be 12pt at 12pt, got {w} — width table likely "
        f"not indexed by WinAnsi byte"
    )


def test_curly_quotes_have_real_widths():
    """Curly quotes (U+2018..201D) measure their actual Helvetica widths.

    quoteleft / quoteright = 222 units each; quotedblleft / quotedblright = 333.
    """
    assert abs(text_width("‘", "Helvetica", 12.0) - 222 * 12 / 1000) < 1e-9
    assert abs(text_width("’", "Helvetica", 12.0) - 222 * 12 / 1000) < 1e-9
    assert abs(text_width("“", "Helvetica", 12.0) - 333 * 12 / 1000) < 1e-9
    assert abs(text_width("”", "Helvetica", 12.0) - 333 * 12 / 1000) < 1e-9


def test_ellipsis_has_real_width():
    """Single-glyph ellipsis (U+2026) is 1000 units in Helvetica."""
    w = text_width("…", "Helvetica", 12.0)
    assert abs(w - 12.0) < 1e-9


def test_to_winansi_byte_handles_known_cases():
    """The codepoint→byte mapping covers the common typographic punctuation."""
    from inkmd.fonts import to_winansi_byte
    assert to_winansi_byte(ord("A")) == ord("A")  # ASCII identity
    assert to_winansi_byte(0x2014) == 0x97  # em dash
    assert to_winansi_byte(0x2013) == 0x96  # en dash
    assert to_winansi_byte(0x2018) == 0x91  # left single quote
    assert to_winansi_byte(0x2019) == 0x92  # right single quote
    assert to_winansi_byte(0x2026) == 0x85  # ellipsis
    assert to_winansi_byte(0x00E9) == 0xE9  # Latin-1 é
    assert to_winansi_byte(0x2603) == ord("?")  # snowman → fallback
