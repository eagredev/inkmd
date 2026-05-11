"""Heading parser + render tests — milestone 0.0.7.

Covers ATX (``# foo``) and Setext (``foo\\n===``) headings, the parser's
edge cases around them, and the renderer's level-to-size mapping plus
per-block spacing.
"""

from __future__ import annotations

from inkmd.ast import Document, Emphasis, Heading, Paragraph, Strong, Text
from inkmd.parser import parse
from inkmd.render import (
    HEADING_SIZES,
    HELVETICA_FAMILY,
    TIMES_FAMILY,
    render_document,
)


# --- ATX parsing ----------------------------------------------------------


def test_atx_h1():
    doc = parse("# Hello")
    assert doc.blocks == (Heading(level=1, inlines=(Text("Hello"),)),)


def test_atx_h2_through_h6():
    for level in range(1, 7):
        md = "#" * level + " Title"
        doc = parse(md)
        assert doc.blocks == (Heading(level=level, inlines=(Text("Title"),)),), f"failed at h{level}"


def test_atx_h7_is_not_a_heading():
    """Seven hashes is not a heading; treat as paragraph."""
    doc = parse("####### Title")
    assert isinstance(doc.blocks[0], Paragraph)


def test_atx_requires_space_after_hashes():
    """``#Title`` is not a heading per CommonMark §4.2."""
    doc = parse("#NoSpace")
    assert isinstance(doc.blocks[0], Paragraph)


def test_atx_empty_heading_allowed():
    """``# `` with no content is a valid empty heading."""
    doc = parse("#")
    assert doc.blocks == (Heading(level=1, inlines=()),)


def test_atx_strips_trailing_closing_hashes():
    doc = parse("## Title ##")
    assert doc.blocks == (Heading(level=2, inlines=(Text("Title"),)),)


def test_atx_preserves_internal_hashes():
    """A ``#`` mid-line that isn't preceded by space is content, not a closer."""
    doc = parse("## Title with # in middle")
    assert doc.blocks == (
        Heading(level=2, inlines=(Text("Title with # in middle"),)),
    )


def test_atx_allows_indent_up_to_three_spaces():
    for indent in range(0, 4):
        doc = parse(" " * indent + "# Title")
        assert isinstance(doc.blocks[0], Heading), f"failed at indent {indent}"


def test_atx_four_space_indent_is_not_heading():
    """Four-space indent is a code block context — not heading."""
    doc = parse("    # NotAHeading")
    # Code blocks aren't implemented yet, so this falls through to paragraph.
    assert isinstance(doc.blocks[0], Paragraph)


def test_atx_with_inline_emphasis():
    doc = parse("# Hello *world*")
    h = doc.blocks[0]
    assert isinstance(h, Heading)
    assert h.level == 1
    assert h.inlines == (Text("Hello "), Emphasis(inlines=(Text("world"),)))


def test_atx_with_inline_strong():
    doc = parse("## Bold **text** here")
    h = doc.blocks[0]
    assert isinstance(h, Heading)
    assert h.inlines == (
        Text("Bold "),
        Strong(inlines=(Text("text"),)),
        Text(" here"),
    )


def test_atx_followed_by_paragraph_separated_by_blank_line():
    doc = parse("# Title\n\nBody text here.")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], Heading)
    assert isinstance(doc.blocks[1], Paragraph)


def test_atx_followed_by_paragraph_no_blank_line():
    """An ATX heading ends immediately; following line starts a paragraph."""
    doc = parse("# Title\nBody")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], Heading)
    assert isinstance(doc.blocks[1], Paragraph)


def test_atx_after_paragraph_no_blank_line():
    """A line of paragraph text followed by an ATX heading: heading wins."""
    doc = parse("Body\n# Title")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], Paragraph)
    assert isinstance(doc.blocks[1], Heading)


# --- Setext parsing -------------------------------------------------------


def test_setext_h1():
    doc = parse("Heading\n=======")
    assert doc.blocks == (Heading(level=1, inlines=(Text("Heading"),)),)


def test_setext_h2():
    doc = parse("Heading\n-------")
    assert doc.blocks == (Heading(level=2, inlines=(Text("Heading"),)),)


def test_setext_h1_single_equals_works():
    """One ``=`` is enough per CommonMark §4.3."""
    doc = parse("Title\n=")
    assert doc.blocks == (Heading(level=1, inlines=(Text("Title"),)),)


def test_setext_multi_line_content_joins():
    """Multiple content lines before underline join with a space."""
    doc = parse("Line one\nLine two\n===")
    assert doc.blocks == (
        Heading(level=1, inlines=(Text("Line one Line two"),)),
    )


def test_setext_underline_indent_allowed():
    """Up to 3 spaces of indent on the underline is fine."""
    doc = parse("Title\n   ===")
    assert isinstance(doc.blocks[0], Heading)


def test_setext_underline_with_trailing_space():
    doc = parse("Title\n===   ")
    assert isinstance(doc.blocks[0], Heading)


def test_setext_underline_with_other_chars_is_not_setext():
    """``===abc`` isn't a setext underline; it's paragraph content."""
    doc = parse("Title\n===abc")
    assert isinstance(doc.blocks[0], Paragraph)


def test_setext_blank_line_breaks_attachment():
    """Blank line between paragraph and ``===`` means the ``===`` is paragraph content."""
    doc = parse("Title\n\n===")
    # First block is a paragraph; the second block is whatever ``===`` parses as
    # (currently a paragraph since we don't recognise thematic breaks yet).
    assert isinstance(doc.blocks[0], Paragraph)
    assert doc.blocks[0].inlines == (Text("Title"),)


def test_setext_with_inline_emphasis():
    doc = parse("Welcome *to* inkmd\n===")
    h = doc.blocks[0]
    assert isinstance(h, Heading)
    assert h.level == 1
    assert h.inlines == (
        Text("Welcome "),
        Emphasis(inlines=(Text("to"),)),
        Text(" inkmd"),
    )


def test_setext_followed_by_paragraph():
    doc = parse("Title\n===\n\nBody.")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], Heading)
    assert isinstance(doc.blocks[1], Paragraph)


# --- Renderer -------------------------------------------------------------


def test_heading_render_uses_bold_face():
    doc = Document(blocks=(Heading(level=1, inlines=(Text("Hi"),)),))
    block = render_document(doc)[0]
    assert block.runs[0].font == HELVETICA_FAMILY.bold


def test_heading_render_uses_level_size():
    for level, size in HEADING_SIZES.items():
        doc = Document(blocks=(Heading(level=level, inlines=(Text("X"),)),))
        block = render_document(doc)[0]
        assert block.runs[0].size == size, f"level {level} got {block.runs[0].size}"


def test_heading_render_in_times_family():
    doc = Document(blocks=(Heading(level=2, inlines=(Text("Hi"),)),))
    block = render_document(doc, family=TIMES_FAMILY)[0]
    assert block.runs[0].font == "Times-Bold"


def test_heading_inline_emphasis_keeps_size():
    """Inline ``*italic*`` inside a heading must stay at heading size."""
    doc = Document(blocks=(
        Heading(level=2, inlines=(
            Text("Hi "),
            Emphasis(inlines=(Text("there"),)),
        )),
    ))
    block = render_document(doc)[0]
    assert block.runs[0].size == HEADING_SIZES[2]
    assert block.runs[1].size == HEADING_SIZES[2]
    # And the inner Emphasis flips bold (heading face) to bold-italic.
    assert block.runs[1].font == HELVETICA_FAMILY.bold_italic


def test_heading_has_space_above_and_below():
    doc = Document(blocks=(Heading(level=1, inlines=(Text("Hi"),)),))
    block = render_document(doc)[0]
    assert block.space_above > 0
    assert block.space_below > 0


def test_paragraph_has_no_extra_spacing():
    doc = Document(blocks=(Paragraph(inlines=(Text("Body."),)),))
    block = render_document(doc)[0]
    assert block.space_above == 0
    assert block.space_below == 0


# --- End-to-end through compile() -----------------------------------------


def test_compile_with_heading_produces_valid_pdf():
    import inkmd
    out = inkmd.compile("# Title\n\nBody.")
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_compile_heading_text_appears_in_stream():
    """The heading text must show up in the PDF byte stream.

    Helvetica-Bold has kerning pairs that may split a single word into
    multiple TJ-array literals; check fragments individually so this is
    robust to the kerning pass.
    """
    import inkmd
    out = inkmd.compile("# zzHeadingzz\n\nBody.")
    # ``zz`` brackets at both ends are kerning-free; check the bracket
    # fragments appear independently. The middle ``Heading`` may be split.
    assert b"zz" in out
    # The 24pt heading font size should be emitted as /F2 24 Tf or similar.
    assert b"24 Tf" in out
