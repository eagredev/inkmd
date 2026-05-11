"""List parser + render tests — milestone 0.0.8 (full CommonMark lists)."""

from __future__ import annotations

from inkmd.ast import (
    Document,
    Emphasis,
    Heading,
    List,
    ListItem,
    Paragraph,
    Strong,
    Text,
)
from inkmd.parser import parse


# --- Parser: unordered, single-level --------------------------------------


def test_simple_bullet_list_dash():
    doc = parse("- one\n- two\n- three")
    assert len(doc.blocks) == 1
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert lst.ordered is False
    assert lst.tight is True
    assert len(lst.items) == 3
    assert lst.items[0].blocks == (Paragraph(inlines=(Text("one"),)),)


def test_simple_bullet_list_asterisk():
    doc = parse("* a\n* b")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert lst.ordered is False
    assert len(lst.items) == 2


def test_simple_bullet_list_plus():
    doc = parse("+ x\n+ y")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert len(lst.items) == 2


def test_different_bullet_markers_split_into_separate_lists():
    """A `-` list followed by a `*` list at the same indent are two lists."""
    doc = parse("- one\n* two")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], List)
    assert isinstance(doc.blocks[1], List)
    assert doc.blocks[0].items[0].blocks == (Paragraph(inlines=(Text("one"),)),)


# --- Parser: ordered ------------------------------------------------------


def test_simple_ordered_list():
    doc = parse("1. one\n2. two\n3. three")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert lst.ordered is True
    assert lst.start == 1
    assert len(lst.items) == 3


def test_ordered_list_arbitrary_start():
    doc = parse("5. five\n6. six")
    lst = doc.blocks[0]
    assert lst.ordered is True
    assert lst.start == 5
    assert len(lst.items) == 2


def test_ordered_paren_delim():
    doc = parse("1) one\n2) two")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert lst.ordered is True


def test_ordered_dot_and_paren_dont_merge():
    """`1.` and `1)` are different list styles (different delimiters)."""
    doc = parse("1. a\n1) b")
    assert len(doc.blocks) == 2


# --- Parser: nesting ------------------------------------------------------


def test_nested_bullet_inside_bullet():
    doc = parse("- outer\n  - inner")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    outer_item = lst.items[0]
    # Outer item has paragraph "outer" plus a nested list.
    assert len(outer_item.blocks) == 2
    inner = outer_item.blocks[1]
    assert isinstance(inner, List)
    assert inner.items[0].blocks == (Paragraph(inlines=(Text("inner"),)),)


def test_nested_two_inner_items():
    """A nested list with multiple items belongs to one nested List, not two."""
    doc = parse("- outer\n    - a\n    - b\n- outer2")
    lst = doc.blocks[0]
    assert len(lst.items) == 2
    inner = lst.items[0].blocks[1]
    assert isinstance(inner, List)
    assert len(inner.items) == 2


def test_nested_ordered_inside_unordered():
    doc = parse("- outer\n  1. inner-a\n  2. inner-b")
    lst = doc.blocks[0]
    inner = lst.items[0].blocks[1]
    assert isinstance(inner, List)
    assert inner.ordered is True
    assert len(inner.items) == 2


def test_three_deep_nesting():
    md = "- a\n  - b\n    - c"
    doc = parse(md)
    outer = doc.blocks[0]
    mid = outer.items[0].blocks[1]
    deep = mid.items[0].blocks[1]
    assert isinstance(deep, List)
    assert deep.items[0].blocks == (Paragraph(inlines=(Text("c"),)),)


# --- Parser: tight vs loose ------------------------------------------------


def test_tight_list_no_blanks():
    doc = parse("- a\n- b")
    assert doc.blocks[0].tight is True


def test_loose_list_blank_between_items():
    doc = parse("- a\n\n- b")
    assert doc.blocks[0].tight is False


def test_inner_list_can_be_loose_independent_of_outer():
    doc = parse("- outer\n  - inner1\n\n  - inner2\n- outer2")
    outer = doc.blocks[0]
    # The blank line inside the outer item makes outer loose too per CommonMark,
    # but the inner list is definitely loose.
    inner = outer.items[0].blocks[1]
    assert inner.tight is False


# --- Parser: lists interrupting paragraphs --------------------------------


def test_bullet_list_after_paragraph_no_blank_line():
    """In CommonMark a bullet list interrupts a paragraph."""
    doc = parse("Some text.\n- item")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], Paragraph)
    assert isinstance(doc.blocks[1], List)


def test_list_followed_by_paragraph():
    doc = parse("- item\n\nParagraph after.")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], List)
    assert isinstance(doc.blocks[1], Paragraph)


# --- Parser: inline content in items --------------------------------------


def test_item_with_emphasis():
    doc = parse("- *italic* item")
    item = doc.blocks[0].items[0]
    assert item.blocks == (
        Paragraph(inlines=(Emphasis(inlines=(Text("italic"),)), Text(" item"))),
    )


def test_item_with_strong():
    doc = parse("- **bold** item")
    item = doc.blocks[0].items[0]
    assert item.blocks == (
        Paragraph(inlines=(Strong(inlines=(Text("bold"),)), Text(" item"))),
    )


# --- Parser: edge cases ---------------------------------------------------


def test_bullet_at_3_space_indent_is_still_top_level_list():
    """Up to 3 spaces of indent before a marker is still top-level."""
    doc = parse("   - item")
    assert isinstance(doc.blocks[0], List)


def test_empty_list_item_is_allowed():
    """A marker with no content is an empty item."""
    doc = parse("-\n- after")
    lst = doc.blocks[0]
    assert len(lst.items) == 2
    assert lst.items[0].blocks == ()


def test_dash_at_start_of_word_is_not_a_marker():
    """A dash without trailing space is not a list marker."""
    doc = parse("-not a list")
    assert isinstance(doc.blocks[0], Paragraph)


# --- Render: tight list ---------------------------------------------------


def test_render_tight_list_emits_one_block_per_item():
    from inkmd.render import render_document

    doc = parse("- a\n- b\n- c")
    blocks = render_document(doc)
    assert len(blocks) == 3
    # Each block has a marker run.
    for b in blocks:
        assert b.marker_runs, "every list item must have a marker"


def test_render_bullet_marker_is_bullet_character():
    from inkmd.render import render_document

    doc = parse("- item")
    block = render_document(doc)[0]
    assert block.marker_runs[0].text == "• "


def test_render_ordered_marker_is_number():
    from inkmd.render import render_document

    doc = parse("1. apple\n2. banana")
    blocks = render_document(doc)
    assert blocks[0].marker_runs[0].text == "1. "
    assert blocks[1].marker_runs[0].text == "2. "


def test_render_ordered_marker_uses_start_number():
    from inkmd.render import render_document

    doc = parse("7. seven\n8. eight")
    blocks = render_document(doc)
    assert blocks[0].marker_runs[0].text == "7. "
    assert blocks[1].marker_runs[0].text == "8. "


def test_render_tight_list_items_are_compact():
    """Sibling items in a tight list set compact=True so paginator skips gap."""
    from inkmd.render import render_document

    doc = parse("- a\n- b\n- c")
    blocks = render_document(doc)
    assert blocks[0].compact is False  # first item starts the list normally
    assert blocks[1].compact is True
    assert blocks[2].compact is True


def test_render_loose_list_items_not_compact():
    from inkmd.render import render_document

    doc = parse("- a\n\n- b")
    blocks = render_document(doc)
    # The list is loose, so item 2 keeps the paragraph_spacing gap.
    assert blocks[1].compact is False


# --- Render: nesting --------------------------------------------------------


def test_render_nested_list_uses_deeper_indent():
    from inkmd.render import LIST_INDENT_PT, render_document

    doc = parse("- outer\n  - inner")
    blocks = render_document(doc)
    # blocks[0] is the outer marker-bearing line; blocks[1] is the inner.
    assert blocks[1].body_indent > blocks[0].body_indent
    # Outer body_indent should be one LIST_INDENT_PT; inner should be two.
    assert blocks[0].body_indent == LIST_INDENT_PT
    assert blocks[1].body_indent == 2 * LIST_INDENT_PT


# --- Compile end-to-end -----------------------------------------------------


def test_compile_with_list_produces_valid_pdf():
    import inkmd

    out = inkmd.compile("- one\n- two\n- three")
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_compile_includes_item_text_in_stream():
    import inkmd

    out = inkmd.compile("- zzapplezz\n- zzbananazz")
    assert b"zz" in out  # robust to kerning splits
    # Bullet character (WinAnsi byte 0x95) should appear in the stream.
    assert b"\x95" in out
