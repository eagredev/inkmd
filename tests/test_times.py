"""Times font family tests — Times-Roman, -Bold, -Italic, -BoldItalic."""

from __future__ import annotations

import pytest

import inkmd
from inkmd.fonts import (
    SUPPORTED_FONTS,
    TIMES_BOLDITALIC_WIDTHS,
    TIMES_BOLD_WIDTHS,
    TIMES_ITALIC_WIDTHS,
    TIMES_ROMAN_WIDTHS,
    kerning_adjustment,
    text_width,
)
from inkmd.render import HELVETICA_FAMILY, TIMES_FAMILY, FAMILIES


# --- Data shape -----------------------------------------------------------


def test_times_faces_are_supported():
    for name in ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"):
        assert name in SUPPORTED_FONTS, f"{name} not in SUPPORTED_FONTS"


def test_times_roman_known_widths():
    """Spot-check published AFM values for Times-Roman."""
    # Times-Roman.afm: M=889, W=944, i=278, space=250
    assert TIMES_ROMAN_WIDTHS[ord("M")] == 889
    assert TIMES_ROMAN_WIDTHS[ord("W")] == 944
    assert TIMES_ROMAN_WIDTHS[ord("i")] == 278
    assert TIMES_ROMAN_WIDTHS[ord(" ")] == 250


def test_times_bold_wider_than_times_roman_for_most_text():
    text = "The quick brown fox"
    w_regular = text_width(text, "Times-Roman", 12.0)
    w_bold = text_width(text, "Times-Bold", 12.0)
    assert w_bold > w_regular


def test_times_italic_has_distinct_widths_from_times_roman():
    """Times-Italic is a redrawn typeface, not a slant — widths differ."""
    # Many glyphs have different widths between Times-Roman and Times-Italic.
    diffs = sum(
        1 for b in range(0x20, 0x7F)
        if TIMES_ROMAN_WIDTHS.get(b) != TIMES_ITALIC_WIDTHS.get(b)
    )
    assert diffs > 30, f"expected many width differences, got {diffs}"


def test_times_bolditalic_distinct_from_times_bold():
    diffs = sum(
        1 for b in range(0x20, 0x7F)
        if TIMES_BOLD_WIDTHS.get(b) != TIMES_BOLDITALIC_WIDTHS.get(b)
    )
    assert diffs > 30


# --- Kerning --------------------------------------------------------------


def test_times_roman_has_kerning_pairs():
    """Times-Roman has its own published kerning table (~2000 pairs)."""
    # 'Te' is a classic kerned pair in Times
    adj = kerning_adjustment("Times-Roman", ord("T"), ord("e"))
    assert adj < 0, f"Te should be kerned closer, got {adj}"


def test_times_italic_has_its_own_kerning():
    """Times-Italic's kerning table is distinct from Times-Roman's."""
    # At least some pair should differ
    found_diff = False
    for left, right in [("T", "e"), ("V", "a"), ("W", "e"), ("A", "V")]:
        a = kerning_adjustment("Times-Roman", ord(left), ord(right))
        b = kerning_adjustment("Times-Italic", ord(left), ord(right))
        if a != b:
            found_diff = True
            break
    assert found_diff, "Times-Italic kerning should differ from Times-Roman somewhere"


# --- Render integration ---------------------------------------------------


def test_family_registry_includes_times_and_helvetica():
    assert "helvetica" in FAMILIES
    assert "times" in FAMILIES


def test_times_family_uses_times_fonts():
    assert TIMES_FAMILY.regular == "Times-Roman"
    assert TIMES_FAMILY.bold == "Times-Bold"
    assert TIMES_FAMILY.italic == "Times-Italic"
    assert TIMES_FAMILY.bold_italic == "Times-BoldItalic"


def test_compile_with_times_family_uses_times_roman():
    data = inkmd.compile("Hello.", family="times")
    # The font dictionary should declare Times-Roman somewhere.
    assert b"/BaseFont /Times-Roman" in data


def test_compile_with_helvetica_uses_helvetica():
    """Default family stays Helvetica."""
    data = inkmd.compile("Hello.")
    # Stream should pick a Helvetica slot for the body run.
    # F1 = Helvetica in our slot table.
    assert b"/F1 12 Tf" in data


def test_compile_with_unknown_family_raises():
    with pytest.raises(ValueError):
        inkmd.compile("Hello.", family="comic-sans")


def test_compile_times_output_is_deterministic():
    runs = [inkmd.compile("Hello — world.", family="times") for _ in range(3)]
    assert all(r == runs[0] for r in runs)


def test_compile_times_includes_typographic_punctuation():
    """Em dash and curly quotes still appear correctly in Times output."""
    data = inkmd.compile("Hello — world.", family="times")
    assert b"\x97" in data  # em dash
