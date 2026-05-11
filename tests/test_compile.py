"""End-to-end compile() tests — milestone 0.0.4.

These tests exercise the full pipeline: markdown text → parser →
render → paginate → PDF bytes. Byte-level assertions verify the PDF
is structurally valid; content assertions verify the input text
survives the pipeline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import inkmd


# --- Public API shape -----------------------------------------------------


def test_compile_returns_bytes():
    out = inkmd.compile("Hello.")
    assert isinstance(out, bytes)


def test_compile_produces_valid_pdf_header():
    assert inkmd.compile("Hello.").startswith(b"%PDF-1.4\n")


def test_compile_produces_valid_pdf_eof():
    assert inkmd.compile("Hello.").rstrip(b"\n").endswith(b"%%EOF")


def test_compile_empty_string_is_valid_pdf():
    """Edge case: empty input still produces a parseable PDF."""
    out = inkmd.compile("")
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


# --- Content preservation -------------------------------------------------


def test_compile_includes_input_text_in_stream():
    """A unique anchor string from the input must appear in the output bytes.

    We pick an anchor with no internal Helvetica kerning pairs so the
    string appears whole inside a single Tj literal rather than split
    across a TJ array.
    """
    out = inkmd.compile("zzAnchorzz")  # no kerning pairs anywhere
    assert b"zzAnchorzz" in out


def test_compile_two_paragraphs_produces_two_lines():
    """Two paragraph blocks → at least two Tm-positioned drawings."""
    out = inkmd.compile("First.\n\nSecond.")
    tm_count = out.count(b" Tm")
    assert tm_count >= 2


def test_compile_unicode_typographic_punctuation_round_trips():
    """Em dash, curly quotes, ellipsis should appear in the stream as WinAnsi bytes."""
    out = inkmd.compile("Hello — world… and ‘curly’ too.")
    assert b"\x97" in out  # em dash
    assert b"\x85" in out  # ellipsis
    assert b"\x92" in out  # right single quote U+2019


# --- Determinism ----------------------------------------------------------


def test_compile_is_deterministic():
    md = "Same input.\n\nProduces same output."
    runs = [inkmd.compile(md) for _ in range(5)]
    assert all(r == runs[0] for r in runs)


# --- render_file ----------------------------------------------------------


def test_render_file_writes_pdf(tmp_path: Path):
    md_path = tmp_path / "in.md"
    pdf_path = tmp_path / "out.pdf"
    md_path.write_text("Hello, world.\n\nSecond paragraph.")
    inkmd.render_file(md_path, pdf_path)
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF-1.4\n")


def test_render_file_accepts_pathlib_and_str(tmp_path: Path):
    md_path = tmp_path / "in.md"
    pdf_path = tmp_path / "out.pdf"
    md_path.write_text("Hello.")
    # str path
    inkmd.render_file(str(md_path), str(pdf_path))
    assert pdf_path.exists()
    pdf_path.unlink()
    # Path object
    inkmd.render_file(md_path, pdf_path)
    assert pdf_path.exists()


def test_render_file_utf8_input(tmp_path: Path):
    """Markdown files are read as UTF-8 regardless of locale."""
    md_path = tmp_path / "in.md"
    pdf_path = tmp_path / "out.pdf"
    md_path.write_text("Café — naïve façade.\n", encoding="utf-8")
    inkmd.render_file(md_path, pdf_path)
    # The é (U+00E9) and em dash should both make it into the stream.
    data = pdf_path.read_bytes()
    assert b"\xe9" in data  # é as WinAnsi byte
    assert b"\x97" in data  # em dash


# --- External validation --------------------------------------------------


def _have_tool(name: str) -> bool:
    try:
        subprocess.run([name, "--version"], capture_output=True, check=False, timeout=5)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _have_tool("qpdf"), reason="qpdf not available")
def test_compile_output_passes_qpdf_check(tmp_path: Path):
    out = tmp_path / "out.pdf"
    out.write_bytes(inkmd.compile("Hello.\n\nWorld."))
    result = subprocess.run(
        ["qpdf", "--check", str(out)], capture_output=True, text=True, check=False
    )
    assert result.returncode in (0, 3), result.stdout + result.stderr


@pytest.mark.skipif(not _have_tool("pdftotext"), reason="pdftotext not available")
def test_compile_output_round_trips_through_pdftotext(tmp_path: Path):
    """pdftotext must extract the input paragraphs back out."""
    out = tmp_path / "out.pdf"
    out.write_bytes(inkmd.compile("First paragraph.\n\nSecond paragraph."))
    result = subprocess.run(
        ["pdftotext", str(out), "-"], capture_output=True, text=True, check=True
    )
    assert "First paragraph" in result.stdout
    assert "Second paragraph" in result.stdout
    # And no warnings printed to stderr.
    assert "Syntax Error" not in result.stderr


@pytest.mark.skipif(not _have_tool("pdftotext"), reason="pdftotext not available")
def test_compile_long_input_paginates(tmp_path: Path):
    """A long enough input should produce a multi-page PDF."""
    md = "\n\n".join(f"Paragraph number {i}." for i in range(150))
    out = tmp_path / "long.pdf"
    out.write_bytes(inkmd.compile(md))
    # Use file(1) to confirm page count.
    if _have_tool("file"):
        result = subprocess.run(
            ["file", str(out)], capture_output=True, text=True, check=True
        )
        import re
        m = re.search(r"(\d+)\s+page", result.stdout)
        assert m is not None
        assert int(m.group(1)) >= 2
