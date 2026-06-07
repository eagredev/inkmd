"""Tests for the embedded-TrueType measurement primitive (embedded_metrics.py).

These exercise the codepoint/glyph-id-keyed sibling of the WinAnsi path. They
reuse S1's synthetic-font builder ``_build_truetype_font`` from
``test_truetype.py`` (imported directly, not re-factored into a shared util:
pytest collects the tests directory so the import resolves, and importing keeps
this file from touching the existing S1 test file at all). The synthetic fonts
carry KNOWN advances and a KNOWN ``units_per_em`` so each measured width can be
asserted exactly against ``advance * size / units_per_em``.

What each test pins:

* scale base is read from the font, not hardcoded 1000 (units_per_em 1000 AND
  2048 with the SAME design advance give different point widths);
* multi-char measurement is the UNKERNED sum of advances;
* a zero-width formatting codepoint is dropped from the sum;
* a codepoint absent from the cmap measures gid-0's real (non-zero) advance,
  not 0;
* the hmtx reused-tail interaction (a gid past numberOfHMetrics measures via the
  reused last advance) - exercising S1 + S2 together.
"""

from __future__ import annotations

import pytest

from inkmd.embedded_metrics import (
    embedded_advance,
    embedded_char_width,
    embedded_text_width,
)
from inkmd.truetype import TrueTypeFont

# Reuse S1's synthetic-font builder rather than re-implementing sfnt packing.
from tests.test_truetype import _build_truetype_font


# --- Fixtures -------------------------------------------------------------
#
# A font where:
#   gid 0 (.notdef) has a REAL, non-zero advance (so the absent-codepoint case
#                   can prove .notdef != 0);
#   gid 1 ('A') and gid 2 ('B') have known advances;
#   gid 3 ('C') is PAST numberOfHMetrics, so it reuses the last explicit
#                   advance (the hmtx reused tail).
#
# Glyph outlines are irrelevant to measurement, so all glyphs are empty: the
# advance comes from hmtx, not glyf. Only num_h_metrics < num_glyphs matters,
# to drive the reused-tail path.


def _measurement_font(units_per_em: int = 1000) -> TrueTypeFont:
    return TrueTypeFont(_build_truetype_font(
        glyphs=[b"", b"", b"", b""],
        advances=[480, 600, 700],   # gid 0/.notdef = 480, gid1 = 600, gid2 = 700
        num_h_metrics=3,            # gid 3 past this -> reuses 700
        units_per_em=units_per_em,
        format4={0x41: 1, 0x42: 2, 0x43: 3},  # A, B, C
    ))


# --- units_per_em scaling (1000 vs 2048) ----------------------------------


def test_char_width_scales_by_units_per_em_1000():
    font = _measurement_font(units_per_em=1000)
    # gid 1 ('A') advance 600 design units, em 1000, size 12.
    assert embedded_char_width(font, 0x41, 12.0) == 600 * 12.0 / 1000


def test_char_width_scales_by_units_per_em_2048():
    font = _measurement_font(units_per_em=2048)
    # SAME design advance (600), but em 2048 -> a different point width. This is
    # the rail: the scale base is read from the font, not hardcoded to 1000.
    assert embedded_char_width(font, 0x41, 12.0) == 600 * 12.0 / 2048


def test_same_advance_different_em_gives_different_width():
    # Belt-and-braces on the scaling rail: identical design advance, two ems.
    f1000 = _measurement_font(units_per_em=1000)
    f2048 = _measurement_font(units_per_em=2048)
    w1000 = embedded_char_width(f1000, 0x41, 12.0)
    w2048 = embedded_char_width(f2048, 0x41, 12.0)
    assert w1000 != w2048
    assert w1000 == pytest.approx(w2048 * 2048 / 1000)


# --- unkerned multi-char sum ----------------------------------------------


def test_text_width_is_unkerned_sum_of_advances():
    font = _measurement_font(units_per_em=1000)
    # "AB" -> the per-char point widths summed left-to-right (600 and 700 design
    # units, each scaled by size/em), with NO pair adjustment. Using the
    # per-char point widths (not (600+700)*size/em in one shot) matches the
    # documented accumulation: text width is the sum of char widths exactly.
    a = embedded_char_width(font, ord("A"), 12.0)
    b = embedded_char_width(font, ord("B"), 12.0)
    assert embedded_text_width(font, "AB", 12.0) == a + b
    # And it is unkerned: a + b with no adjustment is the design-unit total
    # (600 + 700) measured to within float rounding.
    assert embedded_text_width(font, "AB", 12.0) == pytest.approx(
        (600 + 700) * 12.0 / 1000
    )


def test_text_width_equals_sum_of_char_widths():
    # Pins that the string measurement is the per-char sum (unkerned): no kern
    # model can creep in without this diverging. text_width sums design units
    # then scales once (exact, matching WinAnsi), so it agrees with the per-char
    # point-width sum to within float rounding rather than bit-for-bit.
    font = _measurement_font(units_per_em=2048)
    expected = (
        embedded_char_width(font, ord("A"), 10.0)
        + embedded_char_width(font, ord("B"), 10.0)
        + embedded_char_width(font, ord("C"), 10.0)
    )
    assert embedded_text_width(font, "ABC", 10.0) == pytest.approx(expected)
    # Exact form: the integer design-unit total scaled once.
    assert embedded_text_width(font, "ABC", 10.0) == (600 + 700 + 700) * 10.0 / 2048


# --- zero-width formatting codepoint dropped ------------------------------


def test_zero_width_codepoint_measures_zero():
    font = _measurement_font()
    # U+00AD soft hyphen is in fonts._ZERO_WIDTH_CODEPOINTS; it must measure 0
    # even though the font has no glyph for it (which would otherwise hit
    # .notdef and reserve a box).
    assert embedded_char_width(font, 0x00AD, 12.0) == 0.0


def test_zero_width_codepoint_dropped_from_text_sum():
    font = _measurement_font(units_per_em=1000)
    plain = embedded_text_width(font, "AB", 12.0)
    with_softhyphen = embedded_text_width(font, "A­B", 12.0)
    # The soft hyphen contributes nothing, so the two widths are identical.
    assert with_softhyphen == plain


# --- .notdef (absent codepoint) measures gid-0's real, non-zero advance ----


def test_absent_codepoint_measures_notdef_real_advance():
    font = _measurement_font(units_per_em=1000)
    # U+05D0 (Hebrew alef) is not in the cmap -> glyph_id 0 (.notdef). Its width
    # is gid 0's REAL advance (480), scaled - NOT a convenient 0.
    assert font.glyph_id(0x05D0) == 0
    assert embedded_char_width(font, 0x05D0, 12.0) == 480 * 12.0 / 1000


def test_notdef_width_is_nonzero_when_font_has_a_real_box():
    font = _measurement_font(units_per_em=1000)
    # The honesty rail: a missing glyph must reserve real layout space.
    assert embedded_char_width(font, 0x05D0, 12.0) > 0.0


# --- hmtx reused-tail interaction (S1 + S2 together) ----------------------


def test_reused_hmtx_tail_advance_measured():
    font = _measurement_font(units_per_em=1000)
    # gid 3 ('C') is past numberOfHMetrics (3), so advance_width reuses the last
    # explicit advance (700). Measurement must see that reused advance.
    assert font.glyph_id(0x43) == 3
    assert font.advance_width(3) == 700  # S1's reused tail
    assert embedded_char_width(font, 0x43, 12.0) == 700 * 12.0 / 1000  # S2 scales it


# --- design-unit pass-through helper (for S3's /W array) ------------------


def test_embedded_advance_returns_design_units_unscaled():
    font = _measurement_font(units_per_em=2048)
    # Raw design-unit advance, independent of size and units_per_em.
    assert embedded_advance(font, ord("A")) == 600
    assert embedded_advance(font, ord("B")) == 700
    # Absent codepoint -> gid 0's design advance, unscaled.
    assert embedded_advance(font, 0x05D0) == 480
    # Reused-tail gid -> reused last advance.
    assert embedded_advance(font, ord("C")) == 700
