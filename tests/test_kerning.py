"""Kerning tests — milestone 0.0.3.1."""

from __future__ import annotations

import re

from inkmd.fonts import (
    HELVETICA_BOLD_KERNING,
    HELVETICA_KERNING,
    kerning_adjustment,
    text_width,
    to_winansi_byte,
)
from inkmd.layout import Run
from inkmd.pdf import _show_text_operator, styled_pdf, text_pdf


# --- Kerning data ---------------------------------------------------------


def test_helvetica_has_kerning_pairs():
    """The Helvetica kerning table should have ~2700 pairs as published."""
    assert len(HELVETICA_KERNING) > 2000


def test_helvetica_bold_has_kerning_pairs():
    assert len(HELVETICA_BOLD_KERNING) > 2000


def test_helvetica_known_kerning_values():
    """Spot-check published KPX values."""
    assert HELVETICA_KERNING[("W", "e")] == -30
    assert HELVETICA_KERNING[("T", "e")] == -120
    assert HELVETICA_KERNING[("V", "a")] == -70


def test_helvetica_bold_known_kerning_values():
    assert HELVETICA_BOLD_KERNING[("W", "e")] == -35
    assert HELVETICA_BOLD_KERNING[("T", "e")] == -60


def test_kerning_adjustment_returns_zero_when_no_pair():
    """Pairs not in the table return 0, not None or KeyError."""
    assert kerning_adjustment("Helvetica", ord("A"), ord("B")) == 0
    assert kerning_adjustment("Helvetica", ord("z"), ord("z")) == 0


def test_kerning_adjustment_handles_known_pairs():
    assert kerning_adjustment("Helvetica", ord("W"), ord("e")) == -30
    assert kerning_adjustment("Helvetica", ord("T"), ord("e")) == -120


def test_courier_has_no_kerning():
    """Monospace fonts have no kerning pairs."""
    assert kerning_adjustment("Courier", ord("W"), ord("e")) == 0
    assert kerning_adjustment("Courier", ord("T"), ord("e")) == 0


def test_oblique_inherits_helvetica_kerning():
    """Helvetica-Oblique uses the same outlines and the same kerning."""
    for left, right in [("W", "e"), ("T", "e"), ("V", "a")]:
        assert (
            kerning_adjustment("Helvetica-Oblique", ord(left), ord(right))
            == kerning_adjustment("Helvetica", ord(left), ord(right))
        )


# --- Width measurement ----------------------------------------------------


def test_text_width_subtracts_kerning():
    """'We' is 30 units narrower than W + e in Helvetica."""
    # W = 944, e = 556, kerning = -30 → total 1470 → 17.64 at 12pt
    w = text_width("We", "Helvetica", 12.0)
    assert abs(w - 17.64) < 1e-9


def test_text_width_unkerned_pair_unchanged():
    """A pair with no kerning entry produces the simple sum of widths."""
    # 'AB': A=667, B=667, no kerning → 1334 → 16.008 at 12pt
    w = text_width("AB", "Helvetica", 12.0)
    assert abs(w - 16.008) < 1e-9


def test_text_width_multiple_kerning_pairs():
    """Kerning adjustments accumulate."""
    # 'Welcome' kerning:
    #   W-e: -30, e-l: 0, l-c: 0, c-o: 0, o-m: 0, m-e: 0
    # Total reduction: 30 units → 0.36pt at 12pt
    base = sum([944, 556, 222, 500, 556, 833, 556])  # W e l c o m e
    expected = (base - 30) * 12 / 1000
    w = text_width("Welcome", "Helvetica", 12.0)
    assert abs(w - expected) < 1e-9


def test_kerning_does_not_affect_courier():
    """Courier 'Welcome' is 7 * (600/1000) * 12 = 50.4pt regardless."""
    w = text_width("Welcome", "Courier", 12.0)
    assert abs(w - 50.4) < 1e-9


# --- PDF emission ---------------------------------------------------------


def test_show_operator_no_kerning_emits_tj():
    """Text with no kerning pairs emits a simple Tj operator."""
    out = _show_text_operator("AB", "Helvetica")
    assert out == b"(AB) Tj"


def test_show_operator_with_kerning_emits_tj_array():
    """Text with kerning pairs emits a TJ array."""
    out = _show_text_operator("We", "Helvetica")
    # Expect [(W) +30 (e)] TJ — AFM -30 becomes TJ +30 (TJ uses opposite sign).
    assert out.startswith(b"[")
    assert out.endswith(b"] TJ")
    assert b"(W)" in out
    assert b"(e)" in out
    assert b"30" in out


def test_show_operator_courier_never_kerns():
    """Courier produces simple Tj even for normally-kerned pairs."""
    out = _show_text_operator("We", "Courier")
    assert out == b"(We) Tj"


def test_styled_pdf_emits_tj_for_kerned_helvetica():
    """A run in Helvetica with kerning pairs must use TJ, not Tj."""
    data = styled_pdf([[Run("We have", "Helvetica", 12)]])
    # 'We' is kerned (-30) and 'av' is kerned (-40).
    assert b"] TJ" in data


def test_text_pdf_uses_tj_arrays_for_kerned_text():
    """The single-font path also emits TJ when kerning applies."""
    data = text_pdf("Welcome, traveller!")
    assert b"] TJ" in data


def test_tj_array_kerning_sign_is_inverted():
    """AFM KPX -120 should appear as +120 inside a TJ array (PDF sign flip)."""
    # 'Te' has KPX -120 in Helvetica
    out = _show_text_operator("Te", "Helvetica")
    # The number between (T) and (e) should be the positive 120.
    assert b"120" in out
    # Make sure it's not negative.
    assert b"-120" not in out


# --- Regression: the screenshot offenders ---------------------------------


def test_we_is_kerned_in_output():
    """Regression for screenshot bug: 'Welcome' should have a kerning offset."""
    data = styled_pdf([[Run("Welcome", "Helvetica", 12)]])
    # Look for the +30 offset that pulls 'e' toward 'W'.
    # Match any TJ array containing 30 (could be 30 or 30.0 etc, but inkmd
    # emits integers).
    assert b"30" in data
    assert b"] TJ" in data


def test_te_kerns_more_than_we():
    """The published KPX values: Te = -120, We = -30."""
    we_w = text_width("We", "Helvetica", 12.0)
    we_unkerned = (944 + 556) * 12 / 1000
    te_w = text_width("Te", "Helvetica", 12.0)
    te_unkerned = (611 + 556) * 12 / 1000
    we_saving = we_unkerned - we_w
    te_saving = te_unkerned - te_w
    # Te should save more space than We (120 vs 30).
    assert te_saving > we_saving
