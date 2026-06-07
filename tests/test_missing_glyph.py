"""Spine 6: visible missing-glyph marker + deterministic warning.

These tests pin S6's BEHAVIOUR (not its implementation):

* the unifying ``is_renderable_codepoint`` predicate (base-14 OR embedded
  glyph), including the ``cp != 0`` NUL guard;
* the three-way lane split: a glyphless codepoint becomes the visible
  ``[U+XXXX]`` marker routed onto the BASE-14 lane (``embedded=None``),
  never the embedded ``.notdef``;
* both silent paths it kills - no embedded glyph (DejaVu lacks CJK) and no
  embedded font at all (font-less build) - now produce the same marker;
* a renderable embedded codepoint (Cyrillic/Greek DejaVu HAS) is untouched;
* astral codepoints widen to ``[U+XXXXX]`` with no padding bug;
* the ONE-per-compile, sorted+deduped, filterable ``MissingGlyphWarning``;
* the marker run measures on the base-14 path (no parallel measurement);
* determinism: identical bytes AND identical warning text across calls.
"""

from __future__ import annotations

import re
import warnings
import zlib

import pytest

import inkmd
from inkmd import MissingGlyphWarning
from inkmd.embedded import (
    EmbeddedFontRef,
    is_renderable_codepoint,
    load_embedded_font,
    missing_glyph_marker,
    split_run_for_embedding,
    warn_missing_glyphs,
)
from inkmd.layout import Run, run_text_width


# A codepoint the bundled DejaVu genuinely lacks (CJK) and one it has.
_CJK = 0x4E2D  # 中
_CJK2 = 0x6587  # 文
_CYRILLIC = 0x041F  # П (DejaVu HAS)
_ASTRAL = 0x20000  # CJK Ext-B, >= U+10000, DejaVu genuinely lacks it


def _ref() -> EmbeddedFontRef:
    loaded = load_embedded_font()
    assert loaded is not None
    return EmbeddedFontRef(font=loaded[0], font_bytes=loaded[1])


# --- The unifying predicate (with the cp != 0 guard) ----------------------


def test_predicate_base14_is_renderable_with_or_without_font():
    font = _ref().font
    assert is_renderable_codepoint(ord("A"), font)
    assert is_renderable_codepoint(ord("A"), None)  # base-14 needs no font
    assert is_renderable_codepoint(ord("?"), None)  # literal ? is base-14


def test_predicate_embedded_glyph_renderable_only_with_font():
    font = _ref().font
    assert is_renderable_codepoint(_CYRILLIC, font)  # DejaVu has П
    assert not is_renderable_codepoint(_CYRILLIC, None)  # no font -> missing


def test_predicate_cjk_is_unrenderable_with_dejavu():
    font = _ref().font
    assert font.glyph_id(_CJK) == 0  # DejaVu really lacks it
    assert not is_renderable_codepoint(_CJK, font)


def test_predicate_nul_guard_not_falsely_marked():
    # glyph_id(0) == 0 for many fonts, but NUL must NOT be flagged missing.
    font = _ref().font
    assert is_renderable_codepoint(0, font)  # base-14, and cp == 0 guarded
    assert is_renderable_codepoint(0, None)


# --- Marker formatting (padding rule) -------------------------------------


def test_marker_bmp_is_four_hex_digits():
    assert missing_glyph_marker(_CJK) == "[U+4E2D]"
    assert missing_glyph_marker(0x0041) == "[U+0041]"  # min 4, zero-padded


def test_marker_astral_widens_no_padding_bug():
    assert missing_glyph_marker(_ASTRAL) == "[U+20000]"  # 5 digits, no pad
    assert missing_glyph_marker(0x10FFFF) == "[U+10FFFF]"  # 6 digits


# --- The lane split: headline marker (no embedded glyph) ------------------


def test_split_cjk_becomes_marker_on_base14_lane():
    ref = _ref()
    pieces = split_run_for_embedding(
        Run(text="中", font="Helvetica", size=12.0), ref
    )
    assert len(pieces) == 1
    assert pieces[0].text == "[U+4E2D]"
    assert pieces[0].embedded is None  # base-14 lane, NOT the embedded font


def test_compile_cjk_emits_marker_via_winansi_not_notdef():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = inkmd.compile("中")
    assert data[:4] == b"%PDF"
    # The marker text shows on the base-14 show-text path...
    assert _base14_shows(data, "[U+4E2D]")
    # ...and nothing embeds for it (no Type0/FontFile2 from a CJK-only doc).
    assert b"/FontFile2" not in data


# --- Headline marker: font-less / no embedded font ------------------------


def test_split_fontless_non_winansi_becomes_marker_not_question():
    # embedded_ref=None simulates the font-less build: every non-WinAnsi
    # codepoint is unrenderable and must become a marker, not `?`.
    pieces = split_run_for_embedding(
        Run(text="П", font="Helvetica", size=12.0), None
    )
    assert len(pieces) == 1
    assert pieces[0].text == "[U+041F]"  # marker, NOT collapsed to ?
    assert pieces[0].embedded is None


# --- Renderable embedded codepoint is untouched ---------------------------


def test_split_renderable_cyrillic_stays_embedded_no_marker():
    ref = _ref()
    pieces = split_run_for_embedding(
        Run(text="Привет", font="Helvetica", size=12.0), ref
    )
    assert len(pieces) == 1
    assert pieces[0].text == "Привет"  # untouched - not marked
    assert pieces[0].embedded is ref


# --- Mixed runs (the three-way lane split) --------------------------------


def test_split_mixed_cjk_and_ascii():
    ref = _ref()
    pieces = split_run_for_embedding(
        Run(text="中A", font="Helvetica", size=12.0), ref
    )
    # CJK -> marker (base-14), A -> base-14: they coalesce into ONE base-14
    # span; no embedded run, no `?`, no box.
    assert [(p.text, p.embedded) for p in pieces] == [("[U+4E2D]A", None)]


def test_split_mixed_renderable_and_missing_embedded():
    ref = _ref()
    pieces = split_run_for_embedding(
        Run(text="Привет中", font="Helvetica", size=12.0), ref
    )
    # Three-way: Привет embedded, 中 marker on base-14.
    assert [(p.text, p.embedded is ref) for p in pieces] == [
        ("Привет", True),
        ("[U+4E2D]", False),
    ]


def test_split_astral_codepoint_marker():
    ref = _ref()
    pieces = split_run_for_embedding(
        Run(text="\U00020000", font="Helvetica", size=12.0), ref
    )
    assert pieces[0].text == "[U+20000]"  # 5 hex digits, no padding bug
    assert pieces[0].embedded is None


def test_split_nul_not_marked():
    # A NUL is base-14 and guarded by cp != 0: it must NOT become a marker.
    ref = _ref()
    pieces = split_run_for_embedding(
        Run(text="a\x00b", font="Helvetica", size=12.0), ref
    )
    # All base-14 -> identity (no marker injected for the NUL).
    assert len(pieces) == 1
    assert pieces[0].text == "a\x00b"
    assert pieces[0].embedded is None


# --- The warning ----------------------------------------------------------


def test_warning_fires_once_with_sorted_sample_and_counts():
    # Out-of-order, repeated -> one warning, sorted+deduped sample, right
    # counts. 文 (U+6587) appears first in the text but sorts after 中.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        inkmd.compile("文中中")
    glyph_warns = [w for w in caught if w.category is MissingGlyphWarning]
    assert len(glyph_warns) == 1
    msg = str(glyph_warns[0].message)
    assert "2 codepoints" in msg
    assert "3 occurrences" in msg
    # Sorted ascending: U+4E2D before U+6587 (NOT first-seen U+6587 first).
    assert "U+4E2D, U+6587" in msg
    assert msg.index("U+4E2D") < msg.index("U+6587")
    assert "(and 0 more)" in msg


def test_warning_sample_caps_and_reports_remaining():
    # 6 distinct missing CJK codepoints -> sample of 5, "(and 1 more)".
    text = "".join(chr(cp) for cp in range(0x4E00, 0x4E06))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        inkmd.compile(text)
    msg = str(
        [w for w in caught if w.category is MissingGlyphWarning][0].message
    )
    assert "6 codepoints" in msg
    assert "(and 1 more)" in msg
    # Exactly five U+XXXX samples are named.
    assert msg.count("U+4E0") + msg.count("U+4E1") >= 5


def test_no_warning_for_pure_latin():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        inkmd.compile("# Hello\n\nPlain Latin with café & naïve.")
    assert not [w for w in caught if w.category is MissingGlyphWarning]


def test_no_warning_for_renderable_cyrillic():
    # Cyrillic IS renderable (DejaVu) -> no missing-glyph warning.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        inkmd.compile("Привет")
    assert not [w for w in caught if w.category is MissingGlyphWarning]


def test_warning_is_filterable_userwarning_subclass():
    assert issubclass(MissingGlyphWarning, UserWarning)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # warnings become exceptions
        warnings.simplefilter("ignore", MissingGlyphWarning)  # except this
        # Must NOT raise despite filter=error, because we ignore the subclass.
        inkmd.compile("中")


def test_warn_helper_noop_on_empty():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_missing_glyphs([])
    assert not caught


# --- Determinism ----------------------------------------------------------


def test_compile_bytes_and_warning_text_deterministic():
    msgs = []
    payloads = []
    for _ in range(2):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            payloads.append(inkmd.compile("文中中A Привет"))
        msgs.append(
            str(
                [w for w in caught if w.category is MissingGlyphWarning][
                    0
                ].message
            )
        )
    assert payloads[0] == payloads[1]  # byte-identical PDF
    assert msgs[0] == msgs[1]  # identical warning text


# --- Marker width is measured on the base-14 path -------------------------


def test_marker_run_measures_nonzero_base14():
    # A marker run carries embedded=None, so run_text_width measures it as
    # base-14 text (no parallel measurement path). It must be > 0 so
    # wrapping/pagination account for the marker's real width.
    ref = _ref()
    pieces = split_run_for_embedding(
        Run(text="中", font="Helvetica", size=12.0), ref
    )
    marker = pieces[0]
    assert marker.embedded is None
    w = run_text_width(marker)
    assert w > 0
    # And it equals measuring the literal marker text as base-14.
    plain = Run(text="[U+4E2D]", font="Helvetica", size=12.0)
    assert run_text_width(marker) == run_text_width(plain)


# --- Table-cell bypass (documents the deferred MEDIUM, NOT a regression) --


def test_table_cell_cjk_still_question_mark_not_marker():
    """Table cells bypass the S6 marker - SAME pre-S6 silent `?`.

    Documents (does not fix) the deferred MEDIUM: table column widths are
    computed PRE-split, so prepositioned table content never flows through
    ``apply_embedding``'s run-split. A non-WinAnsi/glyphless cell still
    renders ``?``. This is the pre-S6 behaviour, NOT a regression S6 added.
    When the table layout becomes embedding-aware, this test flips to assert
    the marker and the deferred item closes.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = inkmd.compile("| H |\n|---|\n| 中 |\n")
    # No marker in the table cell, and (because the split never sees the
    # prepositioned table text) no warning either.
    assert not _base14_shows(data, "[U+4E2D]")
    assert _base14_shows(data, "?")  # still the silent collapse
    assert not [w for w in caught if w.category is MissingGlyphWarning]


# --- Helper: does a base-14 show-text operator carry this text? -----------


def _base14_shows(data: bytes, needle: str) -> bool:
    """True if ``needle`` appears inside a base-14 ``(...) Tj``/``TJ`` op."""
    chunks = [data]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL):
        try:
            chunks.append(zlib.decompress(m.group(1)))
        except zlib.error:
            continue
    nb = needle.encode("ascii")
    pat = re.compile(rb"\((?:[^()\\]|\\.)*\)\s*T[Jj]")
    for c in chunks:
        for op in pat.finditer(c):
            if nb in op.group(0):
                return True
    return False
