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
