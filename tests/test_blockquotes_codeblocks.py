"""Blockquote + fenced code block tests — milestone 0.0.9."""

from __future__ import annotations

from inkmd.ast import (
    BlockQuote,
    CodeBlock,
    Document,
    Heading,
    List,
    Paragraph,
    Text,
)
from inkmd.parser import parse


# --- Blockquote: parsing --------------------------------------------------


def test_simple_blockquote():
    doc = parse("> hello")
    assert doc.blocks == (BlockQuote(blocks=(Paragraph(inlines=(Text("hello"),)),)),)


def test_blockquote_strips_required_space_after_marker():
    """`>` may be followed by an optional single space; both forms parse the same."""
    doc1 = parse("> hello")
    doc2 = parse(">hello")
    assert doc1 == doc2


def test_blockquote_joins_consecutive_lines_into_paragraph():
    # Soft line breaks survive in the AST as literal newlines.
    doc = parse("> one\n> two\n> three")
    quote = doc.blocks[0]
    assert isinstance(quote, BlockQuote)
    assert quote.blocks == (Paragraph(inlines=(Text("one\ntwo\nthree"),)),)


def test_blockquote_with_internal_blank_line_makes_two_paragraphs():
    doc = parse("> first\n>\n> second")
    quote = doc.blocks[0]
    assert isinstance(quote, BlockQuote)
    assert len(quote.blocks) == 2
    assert all(isinstance(b, Paragraph) for b in quote.blocks)


def test_blockquote_ends_at_blank_unprefixed_line():
    doc = parse("> quoted\n\nAfter quote.")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], BlockQuote)
    assert isinstance(doc.blocks[1], Paragraph)


def test_blockquote_ends_at_unprefixed_line():
    """Without lazy continuation (v0.1), an unprefixed line ends the blockquote."""
    doc = parse("> quoted\nUnprefixed line.")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], BlockQuote)


def test_blockquote_contains_heading():
    doc = parse("> # Quoted heading")
    quote = doc.blocks[0]
    assert isinstance(quote, BlockQuote)
    assert quote.blocks == (Heading(level=1, inlines=(Text("Quoted heading"),)),)


def test_blockquote_contains_list():
    doc = parse("> - item one\n> - item two")
    quote = doc.blocks[0]
    assert isinstance(quote, BlockQuote)
    assert len(quote.blocks) == 1
    assert isinstance(quote.blocks[0], List)
    assert len(quote.blocks[0].items) == 2


def test_nested_blockquote():
    """`> >` produces a blockquote inside a blockquote."""
    doc = parse("> > inner")
    outer = doc.blocks[0]
    assert isinstance(outer, BlockQuote)
    assert isinstance(outer.blocks[0], BlockQuote)
    assert outer.blocks[0].blocks == (Paragraph(inlines=(Text("inner"),)),)


# --- Fenced code block: parsing ------------------------------------------


def test_simple_code_block():
    doc = parse("```\nhello\n```")
    assert doc.blocks == (CodeBlock(content="hello", info=""),)


def test_code_block_with_info_string():
    doc = parse("```python\nprint(1)\n```")
    block = doc.blocks[0]
    assert isinstance(block, CodeBlock)
    assert block.info == "python"
    assert block.content == "print(1)"


def test_code_block_preserves_indentation():
    """Whitespace inside a code block is preserved verbatim."""
    doc = parse("```\n    indented line\n   three-space\n```")
    block = doc.blocks[0]
    assert isinstance(block, CodeBlock)
    assert block.content == "    indented line\n   three-space"


def test_code_block_preserves_blank_lines():
    doc = parse("```\nline one\n\nline three\n```")
    assert doc.blocks[0].content == "line one\n\nline three"


def test_code_block_with_tildes():
    """`~~~` works as a fence character too."""
    doc = parse("~~~\nx = 1\n~~~")
    assert doc.blocks == (CodeBlock(content="x = 1", info=""),)


def test_code_block_close_fence_must_match_char():
    """Backtick-opened fence is NOT closed by tildes."""
    doc = parse("```\ncode\n~~~\nstill code\n```")
    assert doc.blocks[0].content == "code\n~~~\nstill code"


def test_code_block_close_fence_must_be_at_least_as_long():
    """Close fence needs >= opening fence's number of marker chars."""
    doc = parse("````\ncode with ``` inside\n````")
    block = doc.blocks[0]
    assert block.content == "code with ``` inside"


def test_code_block_unclosed_at_eof():
    """An unclosed code block ends at end-of-file."""
    doc = parse("```\nopen forever")
    assert doc.blocks[0].content == "open forever"


def test_code_block_does_not_parse_inline_markdown():
    """Asterisks and backticks inside a code block stay literal."""
    doc = parse("```\n**not bold** `not code`\n```")
    block = doc.blocks[0]
    assert block.content == "**not bold** `not code`"


def test_indented_fence_strips_matching_indent():
    """A fence indented 2 spaces strips up to 2 spaces from each content line."""
    md = "  ```\n  content\n      deeper\n  ```"
    doc = parse(md)
    block = doc.blocks[0]
    assert isinstance(block, CodeBlock)
    # First content line had 2 spaces → 0; second had 6 → 4.
    assert block.content == "content\n    deeper"


def test_fence_after_list_at_column_zero():
    """A column-0 fence following a list (with blank-line separator) must
    open a new code block at the document level, not be absorbed as
    paragraph content.

    Regression: discovered 2026-05-12 while rendering the README hero
    sample. The original feed() short-circuited fence detection when
    list_stack was non-empty; ``` lines after a list were falling through
    to paragraph accumulation, and worse, subsequent text was being
    captured as the *content* of the malformed code block.
    """
    md = (
        "- item one\n"
        "- item two\n"
        "\n"
        "```python\n"
        "x = 1\n"
        "```\n"
        "\n"
        "After.\n"
    )
    doc = parse(md)
    kinds = [type(b).__name__ for b in doc.blocks]
    assert kinds == ["List", "CodeBlock", "Paragraph"]
    code = doc.blocks[1]
    assert code.content == "x = 1"
    assert code.info == "python"


def test_fence_inside_list_item():
    """A fence indented to sit inside a list item should open a code block
    scoped to that item (not at document level)."""
    md = (
        "- item with code:\n"
        "\n"
        "    ```\n"
        "    payload\n"
        "    ```\n"
    )
    doc = parse(md)
    assert len(doc.blocks) == 1
    lst = doc.blocks[0]
    item = lst.items[0]
    item_block_kinds = [type(b).__name__ for b in item.blocks]
    # Paragraph for "item with code:", then a CodeBlock inside the item.
    assert "CodeBlock" in item_block_kinds


# --- Render -----------------------------------------------------------------


def test_render_blockquote_sets_left_rule():
    from inkmd.render import render_document

    doc = parse("> hello")
    block = render_document(doc)[0]
    assert len(block.left_rules) == 1


def test_render_nested_blockquote_stacks_rules():
    """`> > foo` should produce two rules side-by-side, not one.

    Added 0.0.11.6 after torture-test triage. The outer rule sits at
    the outermost x; the inner rule sits one quote-indent to its right.
    """
    from inkmd.render import render_document

    doc = parse("> > inner")
    block = render_document(doc)[0]
    assert len(block.left_rules) == 2
    # Both rules at distinct x positions, outermost first.
    assert block.left_rules[0] < block.left_rules[1]


def test_render_triple_nested_blockquote_stacks_three_rules():
    from inkmd.render import render_document

    doc = parse("> > > deep")
    block = render_document(doc)[0]
    assert len(block.left_rules) == 3
    # Outermost to innermost, monotonically increasing.
    assert block.left_rules[0] < block.left_rules[1] < block.left_rules[2]


def test_render_blockquote_indents_body():
    from inkmd.render import QUOTE_INDENT_PT, render_document

    doc = parse("> hello")
    block = render_document(doc)[0]
    assert block.body_indent >= QUOTE_INDENT_PT


def test_render_code_block_sets_background_fill():
    from inkmd.render import CODE_BG_FILL, render_document

    doc = parse("```\nx\n```")
    block = render_document(doc)[0]
    assert block.background_fill == CODE_BG_FILL


def test_render_code_block_uses_monospace_font():
    from inkmd.render import render_document

    doc = parse("```\nx\n```")
    block = render_document(doc)[0]
    # Single run holds the entire content; its font is the family's monospace.
    assert block.runs[0].font == "Courier"


def test_render_code_block_preserves_lines_flag_set():
    from inkmd.render import render_document

    doc = parse("```\nx\n```")
    block = render_document(doc)[0]
    assert block.preserve_lines is True


# --- End-to-end -----------------------------------------------------------


def test_compile_blockquote_produces_valid_pdf():
    import inkmd

    out = inkmd.compile("> quoted")
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_compile_code_block_produces_valid_pdf():
    import inkmd

    out = inkmd.compile("```\ncode\n```")
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_compile_code_block_emits_filled_rectangle():
    """A code block must emit a ``re f`` (rectangle + fill) operator pair."""
    import inkmd

    out = inkmd.compile("```\nhello\n```")
    assert b" re f" in out


def test_compile_blockquote_emits_rule_rectangle():
    """A blockquote must emit rectangles for the left rule."""
    import inkmd

    out = inkmd.compile("> quoted line")
    assert b" re f" in out


def test_compile_code_block_text_appears_in_stream():
    import inkmd

    out = inkmd.compile("```\nzzAnchorzz\n```")
    # Courier doesn't kern at all, so the anchor stays whole.
    assert b"zzAnchorzz" in out


def test_compile_blockquote_uses_grey_fill_for_rule():
    """The rule fill colour should set the nonstroking RGB to a mid-grey."""
    import inkmd

    out = inkmd.compile("> quoted")
    assert b" rg" in out
