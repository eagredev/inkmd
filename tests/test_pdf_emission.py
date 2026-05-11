"""Milestone 0.0.1 — byte-level tests for the minimum PDF emitter.

These tests verify that the bytes produced by ``hello_world_pdf`` form
a structurally-valid PDF and are deterministic. They do NOT verify that
a real PDF reader can display the file — that's a manual smoke test
(open in a viewer) that the human runs.

The tests deliberately work on raw bytes rather than parsing the PDF
back, because at this stage we want to lock down exactly what we emit.
Once the emitter stabilises we'll add round-trip tests via qpdf.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from inkmd.pdf import hello_world_pdf, _escape_pdf_string


# --- structural validity ---------------------------------------------------


def test_starts_with_pdf_header():
    data = hello_world_pdf()
    assert data.startswith(b"%PDF-1.4\n")


def test_has_binary_marker_after_header():
    """The four high-bit bytes after the header tell tools the file is binary.

    Without this, some transfer protocols mangle line endings on the
    way through. Adobe's PDF Reference recommends emitting them.
    """
    data = hello_world_pdf()
    # Header is 9 bytes ('%PDF-1.4\n'); next line should be '%' followed
    # by four bytes all > 0x7f, then '\n'.
    assert data[9:10] == b"%"
    assert all(b > 0x7F for b in data[10:14])
    assert data[14:15] == b"\n"


def test_ends_with_eof_marker():
    data = hello_world_pdf()
    # %%EOF may be followed by an optional newline.
    assert data.rstrip(b"\n").endswith(b"%%EOF")


def test_contains_six_indirect_objects():
    """Catalog, Pages tree, Page, Font, Content stream — five objects + trailer.

    The trailer is not an indirect object, so we expect exactly five
    '<N> 0 obj' markers in the body.
    """
    data = hello_world_pdf()
    matches = re.findall(rb"\n(\d+) 0 obj\n", data)
    assert matches == [b"1", b"2", b"3", b"4", b"5"]


def test_xref_table_has_correct_entry_count():
    """xref should declare 6 entries: the free-list head + 5 in-use objects."""
    data = hello_world_pdf()
    xref_block = data.split(b"xref\n", 1)[1]
    header_line = xref_block.split(b"\n", 1)[0]
    assert header_line == b"0 6"


def test_xref_offsets_point_at_real_objects():
    """Each xref offset (except the free-list head) should land on '<N> 0 obj'."""
    data = hello_world_pdf()
    xref_section = data.split(b"\nxref\n", 1)[1].split(b"\ntrailer", 1)[0]
    lines = xref_section.split(b"\n")
    # lines[0] is '0 6'; lines[1] is the free-list head; lines[2..6] are real objects.
    for i, line in enumerate(lines[2:7], start=1):
        offset = int(line[:10])
        expected = f"{i} 0 obj\n".encode("ascii")
        assert data[offset:offset + len(expected)] == expected, (
            f"xref entry {i} (offset {offset}) does not point at '{expected!r}'"
        )


def test_trailer_root_points_at_catalog():
    data = hello_world_pdf()
    trailer = data.split(b"trailer\n", 1)[1]
    assert b"/Root 1 0 R" in trailer


def test_trailer_size_matches_object_count():
    data = hello_world_pdf()
    trailer = data.split(b"trailer\n", 1)[1]
    assert b"/Size 6" in trailer


def test_startxref_offset_lands_on_xref_keyword():
    data = hello_world_pdf()
    m = re.search(rb"startxref\n(\d+)\n", data)
    assert m is not None
    offset = int(m.group(1))
    assert data[offset:offset + 5] == b"xref\n"[:5]


# --- content checks --------------------------------------------------------


def test_helvetica_font_declared():
    data = hello_world_pdf()
    assert b"/BaseFont /Helvetica" in data
    assert b"/Subtype /Type1" in data


def test_page_mediabox_letter():
    data = hello_world_pdf(page_size="letter")
    assert b"/MediaBox [0 0 612 792]" in data


def test_page_mediabox_a4():
    data = hello_world_pdf(page_size="A4")
    assert b"/MediaBox [0 0 595 842]" in data


def test_content_stream_contains_text():
    data = hello_world_pdf(text="Hello, world!")
    # The string should appear in PDF-literal form inside a content stream.
    assert b"(Hello, world!) Tj" in data


def test_content_stream_uses_text_object():
    data = hello_world_pdf()
    assert b"BT\n" in data
    assert b"ET" in data


# --- determinism -----------------------------------------------------------


def test_byte_identical_across_runs():
    """Same input must produce byte-identical output, every time."""
    runs = [hello_world_pdf() for _ in range(5)]
    assert all(r == runs[0] for r in runs)


def test_different_text_produces_different_bytes():
    a = hello_world_pdf(text="hello")
    b = hello_world_pdf(text="goodbye")
    assert a != b


def test_different_page_size_produces_different_bytes():
    a = hello_world_pdf(page_size="letter")
    b = hello_world_pdf(page_size="A4")
    assert a != b


# --- string escaping -------------------------------------------------------


def test_escape_parens():
    assert _escape_pdf_string("a (b) c") == "a \\(b\\) c"


def test_escape_backslash():
    assert _escape_pdf_string("a\\b") == "a\\\\b"


def test_escape_text_in_pdf():
    """Parens in text should be escaped inside the content stream."""
    data = hello_world_pdf(text="hello (world)")
    assert b"(hello \\(world\\)) Tj" in data


# --- external validation (best-effort, skipped if tools unavailable) -------


def _have_tool(name: str) -> bool:
    try:
        subprocess.run([name, "--version"], capture_output=True, check=False, timeout=5)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _have_tool("file"), reason="`file` tool not available")
def test_file_command_recognises_pdf(tmp_path: Path):
    out = tmp_path / "hello.pdf"
    out.write_bytes(hello_world_pdf())
    result = subprocess.run(["file", str(out)], capture_output=True, text=True, check=True)
    assert "PDF document" in result.stdout, result.stdout


@pytest.mark.skipif(not _have_tool("qpdf"), reason="qpdf not available")
def test_qpdf_check_passes(tmp_path: Path):
    out = tmp_path / "hello.pdf"
    out.write_bytes(hello_world_pdf())
    result = subprocess.run(
        ["qpdf", "--check", str(out)], capture_output=True, text=True, check=False
    )
    # qpdf --check returns 0 on clean, 3 on warnings (we'll accept warnings
    # in v0.1 since we don't emit /ID or compression — these are advisory).
    assert result.returncode in (0, 3), (
        f"qpdf reported errors:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
