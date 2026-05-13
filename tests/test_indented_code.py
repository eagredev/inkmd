"""Indented code block tests (CommonMark section 4.4).

A line indented by 4 or more spaces, at the document level, with no
open paragraph that could absorb it as lazy continuation, opens an
indented code block. The block continues for as long as subsequent
lines are themselves indented at least 4 spaces (or are blank).
Blank lines inside the block are preserved; trailing blank lines at
the end of the block are dropped.

inkmd's v0.2 implementation covers document-level indented code only.
Indented code inside list items is more involved (the 4-space indent
is measured relative to the item content column) and is queued for
v0.3 — see deferred-work memory and conformance reports.
"""

from __future__ import annotations

import inkmd
from inkmd.ast import CodeBlock, Paragraph
from inkmd.parser import parse


def _blocks(md: str):
    return parse(md).blocks


# --- Basic recognition ---------------------------------------------------


def test_four_spaces_opens_code_block():
    blocks = _blocks("    code\n")
    assert isinstance(blocks[0], CodeBlock)
    assert blocks[0].content == "code\n"
    assert blocks[0].info == ""


def test_three_spaces_does_not_open():
    """Only 4+ spaces qualifies; 3 spaces is a normal paragraph."""
    blocks = _blocks("   not code\n")
    assert isinstance(blocks[0], Paragraph)


def test_five_spaces_keeps_one_space_in_content():
    """Indent past the first 4 spaces is content."""
    blocks = _blocks("     deep\n")
    assert blocks[0].content == " deep\n"


def test_multiline_block():
    blocks = _blocks("    line one\n    line two\n    line three\n")
    assert blocks[0].content == "line one\nline two\nline three\n"


# --- Block boundaries ----------------------------------------------------


def test_unindented_line_closes_block():
    blocks = _blocks("    code\nparagraph after\n")
    assert isinstance(blocks[0], CodeBlock)
    assert blocks[0].content == "code\n"
    assert isinstance(blocks[1], Paragraph)


def test_blank_between_indented_lines_kept_inside_block():
    blocks = _blocks("    line one\n\n    line two\n")
    assert isinstance(blocks[0], CodeBlock)
    assert blocks[0].content == "line one\n\nline two\n"


def test_trailing_blank_lines_dropped():
    blocks = _blocks("    code\n\n\nparagraph\n")
    assert blocks[0].content == "code\n"
    assert isinstance(blocks[1], Paragraph)


def test_eof_closes_block():
    blocks = _blocks("    code\n")
    assert isinstance(blocks[0], CodeBlock)


# --- Lazy continuation precedence ----------------------------------------


def test_indented_line_after_paragraph_is_lazy_continuation():
    """An indented line following an open paragraph continues the paragraph."""
    blocks = _blocks("paragraph\n    indented continuation\n")
    assert len(blocks) == 1
    assert isinstance(blocks[0], Paragraph)


def test_indented_after_blank_is_code():
    """A blank closes the paragraph, so the next indented line is code."""
    blocks = _blocks("paragraph\n\n    code\n")
    assert isinstance(blocks[0], Paragraph)
    assert isinstance(blocks[1], CodeBlock)


# --- Content preservation -----------------------------------------------


def test_atx_marker_inside_code_is_literal():
    blocks = _blocks("    # not a heading\n")
    assert isinstance(blocks[0], CodeBlock)
    assert blocks[0].content == "# not a heading\n"


def test_list_marker_inside_code_is_literal():
    blocks = _blocks("    - not a list\n")
    assert isinstance(blocks[0], CodeBlock)
    assert blocks[0].content == "- not a list\n"


def test_emphasis_markers_inside_code_are_literal():
    blocks = _blocks("    *star* and _underscore_\n")
    assert isinstance(blocks[0], CodeBlock)
    assert "*star*" in blocks[0].content


# --- End-to-end PDF ------------------------------------------------------


def test_pdf_indented_code_renders():
    pdf = inkmd.compile("    function foo() {}\n")
    assert pdf.startswith(b"%PDF-")
