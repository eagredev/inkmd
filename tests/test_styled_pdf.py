"""styled_pdf byte-level tests — milestone 0.0.3."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from inkmd.layout import Run
from inkmd.pdf import (
    FONT_SLOTS,
    _encode_pdf_literal,
    encode_winansi,
    styled_pdf,
)


# --- WinAnsi encoding ------------------------------------------------------


def test_winansi_ascii_identity():
    assert encode_winansi("Hello, world!") == b"Hello, world!"


def test_winansi_em_dash_maps_to_0x97():
    # U+2014 (em dash) → byte 0x97 in WinAnsi
    assert encode_winansi("a—b") == b"a\x97b"


def test_winansi_curly_quote_maps_to_0x92():
    # U+2019 (right single quote) → byte 0x92
    assert encode_winansi("don’t") == b"don\x92t"


def test_winansi_ellipsis_maps_to_0x85():
    assert encode_winansi("wait…") == b"wait\x85"


def test_winansi_unknown_codepoint_becomes_question_mark():
    # U+2603 SNOWMAN has no WinAnsi mapping.
    assert encode_winansi("a☃b") == b"a?b"


def test_encode_pdf_literal_escapes_parens():
    assert _encode_pdf_literal("a (b) c") == b"a \\(b\\) c"


def test_encode_pdf_literal_escapes_backslash():
    assert _encode_pdf_literal("a\\b") == b"a\\\\b"


def test_encode_pdf_literal_handles_unicode_and_parens():
    assert _encode_pdf_literal("(—)") == b"\\(\x97\\)"


# --- structural validity ---------------------------------------------------


def test_styled_pdf_starts_with_pdf_header():
    data = styled_pdf([[Run("hello", "Helvetica", 12)]])
    assert data.startswith(b"%PDF-1.4\n")


def test_styled_pdf_ends_with_eof():
    data = styled_pdf([[Run("hello", "Helvetica", 12)]])
    assert data.rstrip(b"\n").endswith(b"%%EOF")


def test_styled_pdf_declares_all_four_fonts():
    """Every styled PDF declares F1..F4 mapped to the four standard fonts."""
    data = styled_pdf([[Run("hello", "Helvetica", 12)]])
    for font_name in FONT_SLOTS:
        assert f"/BaseFont /{font_name}".encode("ascii") in data


def test_styled_pdf_resource_dict_lists_all_slots():
    data = styled_pdf([[Run("hello", "Helvetica", 12)]])
    for slot in FONT_SLOTS.values():
        assert f"/{slot} ".encode("ascii") in data


def test_styled_pdf_emits_font_switches_in_stream():
    """Mixed-style paragraph should produce multiple /Fn ... Tf operators."""
    runs = [
        Run("plain ", "Helvetica", 12),
        Run("bold ", "Helvetica-Bold", 12),
        Run("italic", "Helvetica-Oblique", 12),
    ]
    data = styled_pdf([runs])
    # All three slot prefixes should appear in Tf operators.
    assert re.search(rb"/F1 \d+(\.\d+)? Tf", data)
    assert re.search(rb"/F2 \d+(\.\d+)? Tf", data)
    assert re.search(rb"/F3 \d+(\.\d+)? Tf", data)


def test_styled_pdf_omits_redundant_font_switches():
    """Two adjacent runs in the same font/size produce only one Tf."""
    runs = [
        Run("alpha ", "Helvetica", 12),
        Run("beta ", "Helvetica", 12),
        Run("gamma", "Helvetica", 12),
    ]
    data = styled_pdf([runs])
    # Only F1 Tf should appear; never F2/F3/F4.
    f1_count = len(re.findall(rb"/F1 \d+(?:\.\d+)? Tf", data))
    f234_count = len(re.findall(rb"/F[234] \d+(?:\.\d+)? Tf", data))
    assert f1_count == 1, f"expected exactly 1 F1 Tf, got {f1_count}"
    assert f234_count == 0


def test_styled_pdf_byte_identical_across_runs():
    runs = [
        Run("hello ", "Helvetica", 12),
        Run("world", "Helvetica-Bold", 12),
    ]
    runs_list = [runs for _ in range(5)]
    outputs = [styled_pdf([r]) for r in runs_list]
    assert all(o == outputs[0] for o in outputs)


def test_styled_pdf_empty_input():
    data = styled_pdf([])
    assert data.startswith(b"%PDF-1.4\n")
    assert data.rstrip(b"\n").endswith(b"%%EOF")


def test_styled_pdf_with_em_dash():
    """Em dash should pass through as the WinAnsi byte, not crash."""
    runs = [Run("hello — world", "Helvetica", 12)]
    data = styled_pdf([runs])
    # Look for byte 0x97 inside the content stream.
    assert b"\x97" in data


def test_font_dict_declares_winansi_encoding():
    """All four fonts must declare /Encoding /WinAnsiEncoding.

    Without this, PDF readers default to StandardEncoding, which leaves
    bytes 0x80..0x9F (em dash, curly quotes, ellipsis, etc.) undefined.
    Glyphs render as blank instead of as their typographic punctuation.
    Caught by visual inspection during milestone 0.0.3; this test locks
    the fix in place.
    """
    data = styled_pdf([[Run("hello", "Helvetica", 12)]])
    # Every BaseFont declaration must be followed by a WinAnsiEncoding.
    base_fonts = re.findall(rb"/BaseFont /(\S+)", data)
    assert len(base_fonts) == 4, base_fonts
    # Count WinAnsiEncoding occurrences — must match font count.
    assert data.count(b"/Encoding /WinAnsiEncoding") == 4


# --- external validators ---------------------------------------------------


def _have_tool(name: str) -> bool:
    try:
        subprocess.run([name, "--version"], capture_output=True, check=False, timeout=5)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _have_tool("file"), reason="`file` tool not available")
def test_styled_pdf_recognised_by_file(tmp_path: Path):
    runs = [
        Run("Welcome to ", "Helvetica", 12),
        Run("inkmd", "Helvetica-Bold", 12),
        Run(" — a markdown ", "Helvetica", 12),
        Run("compiler", "Helvetica-Oblique", 12),
        Run(" written in pure ", "Helvetica", 12),
        Run("Python", "Courier", 12),
        Run(".", "Helvetica", 12),
    ]
    out = tmp_path / "styled.pdf"
    out.write_bytes(styled_pdf([runs]))
    result = subprocess.run(
        ["file", str(out)], capture_output=True, text=True, check=True
    )
    assert "PDF document" in result.stdout


@pytest.mark.skipif(not _have_tool("qpdf"), reason="qpdf not available")
def test_styled_pdf_qpdf_check(tmp_path: Path):
    runs_per_para = [
        [
            Run(f"Paragraph {i} starts ", "Helvetica", 12),
            Run("bold", "Helvetica-Bold", 12),
            Run(" and ends with ", "Helvetica", 12),
            Run("code", "Courier", 12),
            Run(".", "Helvetica", 12),
        ]
        for i in range(40)
    ]
    out = tmp_path / "styled.pdf"
    out.write_bytes(styled_pdf(runs_per_para))
    result = subprocess.run(
        ["qpdf", "--check", str(out)], capture_output=True, text=True, check=False
    )
    assert result.returncode in (0, 3), result.stdout + result.stderr
