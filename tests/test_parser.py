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


def test_parse_internal_newlines_become_spaces():
    """Per CommonMark, a soft line break inside a paragraph joins with a space."""
    doc = parse("Line one\nLine two\nLine three")
    assert doc.blocks[0].inlines == (Text("Line one Line two Line three"),)


def test_parse_internal_trailing_whitespace_collapsed():
    doc = parse("Line one   \nLine two")
    # Trailing spaces stripped; lines joined with one space.
    assert doc.blocks[0].inlines == (Text("Line one Line two"),)


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
