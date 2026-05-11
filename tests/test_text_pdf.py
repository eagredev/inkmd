"""text_pdf tests — milestone 0.0.2: multi-page byte-level emission."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from inkmd.pdf import text_pdf


# --- structural validity ---------------------------------------------------


def test_short_text_produces_valid_pdf():
    data = text_pdf("Hello, world!")
    assert data.startswith(b"%PDF-1.4\n")
    assert data.rstrip(b"\n").endswith(b"%%EOF")


def test_short_text_is_single_page():
    """One paragraph that fits on one page should emit a single Page object."""
    data = text_pdf("Just a short line.")
    # Count Page objects (not Pages tree) by their /Type /Page declaration
    # — exclude /Type /Pages.
    n_page = len(re.findall(rb"/Type /Page[^s]", data))
    assert n_page == 1


def test_long_text_produces_multiple_pages():
    """Many paragraphs must spill across pages."""
    paragraphs = "\n\n".join(f"Paragraph number {i} of many." for i in range(200))
    data = text_pdf(paragraphs)
    n_page = len(re.findall(rb"/Type /Page[^s]", data))
    assert n_page >= 2


def test_pages_tree_kids_count_matches_pages():
    paragraphs = "\n\n".join(f"P{i}" for i in range(150))
    data = text_pdf(paragraphs)
    pages_obj = re.search(rb"/Type /Pages /Kids \[([^\]]+)\] /Count (\d+)", data)
    assert pages_obj is not None
    kid_refs = pages_obj.group(1).split()
    count = int(pages_obj.group(2))
    # Each kid is "N 0 R" — 3 tokens. So token count must be 3 * count.
    assert len(kid_refs) == 3 * count


def test_every_page_has_content_stream():
    """Each Page object must reference a Contents stream object that exists."""
    data = text_pdf("\n\n".join(f"para {i}" for i in range(80)))
    # Page objects look like '/Type /Page /Parent ... /Contents N 0 R >>'.
    # Resource dicts contain '>>' internally, so we can't anchor on '>'.
    # Match /Type /Page followed (eventually) by /Contents.
    page_blocks = re.findall(
        rb"/Type /Page [^a-z].*?/Contents (\d+) 0 R", data, re.DOTALL
    )
    assert page_blocks, "no Page objects found"
    for contents_n in page_blocks:
        expected_header = b"\n" + contents_n + b" 0 obj\n"
        assert expected_header in data


def test_text_appears_in_output():
    """Text should appear in the content stream.

    Kerning may break a string into fragments across a TJ array, so we
    only assert that non-kerned anchor substrings are present and that
    some show operator (Tj or TJ) is emitted.
    """
    data = text_pdf("Hello, world!")
    # 'Hello' has no internal kerning pairs in Helvetica; safe as an anchor.
    assert b"Hello" in data
    # 'world' contains kerned 'wo' and 'rl' pairs, so check non-kerned anchors.
    assert b"orld" in data or b"or" in data or b"ld" in data
    assert b" Tj" in data or b" TJ" in data


def test_handles_empty_input():
    """Empty input should still produce a valid (empty) PDF."""
    data = text_pdf("")
    assert data.startswith(b"%PDF-1.4\n")
    assert data.rstrip(b"\n").endswith(b"%%EOF")


def test_paragraph_separation_via_blank_lines():
    """Two paragraphs should produce two distinct show operations.

    Each paragraph emits its own Tm-positioned show operator. With
    kerning the string fragments inside a TJ array may not match the
    original word literally, so we count show operators per paragraph
    instead.
    """
    data = text_pdf("First paragraph.\n\nSecond paragraph.")
    # Two paragraphs → two lines on the page → two Tm operations.
    tm_count = data.count(b" Tm")
    assert tm_count == 2, f"expected 2 Tm operators, got {tm_count}"
    # Anchor strings from each paragraph that have no internal kerning.
    assert b"First" in data
    assert b"Second" in data


# --- determinism -----------------------------------------------------------


def test_byte_identical_across_runs_single_page():
    runs = [text_pdf("Hello, world!") for _ in range(5)]
    assert all(r == runs[0] for r in runs)


def test_byte_identical_across_runs_multi_page():
    text = "\n\n".join(f"Paragraph {i}." for i in range(100))
    runs = [text_pdf(text) for _ in range(5)]
    assert all(r == runs[0] for r in runs)


# --- external validation ---------------------------------------------------


def _have_tool(name: str) -> bool:
    try:
        subprocess.run([name, "--version"], capture_output=True, check=False, timeout=5)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _have_tool("file"), reason="`file` tool not available")
def test_multi_page_pdf_recognised_by_file(tmp_path: Path):
    text = "\n\n".join(f"Paragraph {i}." for i in range(100))
    out = tmp_path / "multi.pdf"
    out.write_bytes(text_pdf(text))
    result = subprocess.run(["file", str(out)], capture_output=True, text=True, check=True)
    assert "PDF document" in result.stdout
    # file should also report page count when it can.
    match = re.search(r"(\d+)\s+page", result.stdout)
    if match:
        assert int(match.group(1)) >= 2


@pytest.mark.skipif(not _have_tool("qpdf"), reason="qpdf not available")
def test_multi_page_qpdf_check(tmp_path: Path):
    text = "\n\n".join(f"Paragraph {i}." for i in range(100))
    out = tmp_path / "multi.pdf"
    out.write_bytes(text_pdf(text))
    result = subprocess.run(
        ["qpdf", "--check", str(out)], capture_output=True, text=True, check=False
    )
    assert result.returncode in (0, 3), (
        f"qpdf failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


# --- column wrapping in PDF output -----------------------------------------


def test_long_paragraph_produces_multiple_text_strings():
    """A paragraph wider than the column must appear as multiple show operations.

    Each wrapped line emits one Tj or TJ via Tm-positioned drawing,
    so the count of show operators on the page should match the
    visual line count.
    """
    long = " ".join(["word"] * 200)
    data = text_pdf(long)
    n_show = data.count(b" Tj") + data.count(b" TJ")
    assert n_show >= 2, f"expected multiple wrapped lines, got {n_show}"


def test_text_pdf_font_declares_winansi_encoding():
    """The Helvetica font dict must declare /Encoding /WinAnsiEncoding.

    Without this, typographic punctuation (em dash, curly quotes, etc.)
    in user text renders as blank glyphs in PDF readers.
    """
    data = text_pdf("hello world")
    assert b"/Encoding /WinAnsiEncoding" in data


def test_text_pdf_em_dash_appears_in_stream():
    """An em dash in the input text must end up as byte 0x97 in the content stream."""
    data = text_pdf("hello — world")
    assert b"\x97" in data
