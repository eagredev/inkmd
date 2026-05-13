"""Parser tests — milestone 0.0.4: plain paragraphs only."""

from __future__ import annotations

from inkmd.ast import Document, Paragraph, Text
from inkmd.parser import _normalise, parse


# --- _normalise -----------------------------------------------------------


def test_normalise_crlf_to_lf():
    assert _normalise("a\r\nb") == "a\nb"


def test_normalise_standalone_cr_to_lf():
    assert _normalise("a\rb") == "a\nb"


def test_normalise_mixed_line_endings():
    assert _normalise("a\r\nb\rc\nd") == "a\nb\nc\nd"


def test_normalise_tabs_to_four_spaces():
    assert _normalise("a\tb") == "a   b"  # tab at col 1 → 3 spaces to next tab-stop


def test_normalise_null_to_replacement():
    """CommonMark §2.3: U+0000 is replaced with U+FFFD."""
    out = _normalise("a\x00b")
    assert "\x00" not in out
    assert "�" in out


# --- parse: single paragraph ----------------------------------------------


def test_parse_single_paragraph():
    doc = parse("Hello, world.")
    assert isinstance(doc, Document)
    assert len(doc.blocks) == 1
    p = doc.blocks[0]
    assert isinstance(p, Paragraph)
    assert p.inlines == (Text("Hello, world."),)


def test_parse_empty_input_yields_empty_document():
    assert parse("") == Document(blocks=())


def test_parse_only_whitespace_yields_empty_document():
    assert parse("   \n\n   \n").blocks == ()


def test_parse_trailing_newline_does_not_create_empty_block():
    doc = parse("Hello.\n")
    assert len(doc.blocks) == 1


# --- parse: multiple paragraphs -------------------------------------------


def test_parse_two_paragraphs_blank_separated():
    doc = parse("First.\n\nSecond.")
    assert len(doc.blocks) == 2
    assert doc.blocks[0].inlines == (Text("First."),)
    assert doc.blocks[1].inlines == (Text("Second."),)


def test_parse_three_paragraphs():
    doc = parse("One.\n\nTwo.\n\nThree.")
    assert len(doc.blocks) == 3


def test_parse_multiple_blank_lines_still_one_separator():
    """CommonMark: any number of blank lines separates blocks the same way."""
    doc = parse("First.\n\n\n\nSecond.")
    assert len(doc.blocks) == 2


# --- parse: line joining within a paragraph -------------------------------


def test_parse_internal_newlines_preserved_as_soft_breaks():
    """A soft line break inside a paragraph is preserved as a literal '\\n'
    in the AST. Per CommonMark 0.31.2 §6.9, the AST carries the newline;
    HTML renderers emit the newline as markup (browsers collapse it to a
    space); PDF / printed renderers also collapse it to a space at layout
    time. The information is preserved so any consumer can decide."""
    doc = parse("Line one\nLine two\nLine three")
    assert doc.blocks[0].inlines == (Text("Line one\nLine two\nLine three"),)


def test_parse_internal_trailing_whitespace_becomes_hard_break():
    """Two-or-more trailing spaces before a newline are the CommonMark
    hard-break marker (section 6.7). The result is a HardBreak inline
    node, not a soft-break newline."""
    from inkmd.ast import HardBreak

    doc = parse("Line one   \nLine two")
    inlines = doc.blocks[0].inlines
    assert inlines == (
        Text("Line one"),
        HardBreak(),
        Text("Line two"),
    )


def test_parse_single_trailing_space_stays_soft_break():
    """One trailing space is not enough for a hard break; the newline
    is a soft break and the trailing space is stripped per spec."""
    doc = parse("Line one \nLine two")
    inlines = doc.blocks[0].inlines
    assert inlines == (Text("Line one\nLine two"),)


# --- parse: AST shape -----------------------------------------------------


def test_parse_blocks_is_tuple_not_list():
    """Document.blocks must be a tuple so the AST is hashable/immutable."""
    assert isinstance(parse("a").blocks, tuple)


def test_parse_inlines_is_tuple_not_list():
    assert isinstance(parse("a").blocks[0].inlines, tuple)


def test_document_is_hashable():
    """Frozen dataclasses + tuples → Document instances are hashable."""
    a = parse("Hello.")
    b = parse("Hello.")
    assert a == b
    assert hash(a) == hash(b)


def test_document_equality_distinguishes_paragraphs():
    assert parse("Hello.") != parse("Goodbye.")
