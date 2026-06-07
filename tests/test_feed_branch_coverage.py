"""Branch-coverage tests for `_BlockParser.feed`.

These tests target decision arms of `_BlockParser.feed` (parser.py) that the
existing suite did not exercise. Each test drives one previously-uncovered
branch with the minimal markdown that reaches it, and asserts on the PARSED
AST (observable behaviour), never on internal parser state, so they survive
the upcoming refactor that splits `feed` along its three seams.

Branch references in the docstrings are line numbers in parser.py at the time
of writing (v0.3.0); they are navigation aids, not assertions about layout.
"""

from __future__ import annotations

from inkmd.ast import (
    BlockQuote,
    CodeBlock,
    Heading,
    HtmlBlock,
    List,
    Paragraph,
    Table,
    ThematicBreak,
)
from inkmd.parser import parse


def _text(inlines) -> str:
    """Flatten inline nodes to their concatenated literal text."""
    out: list[str] = []
    for node in inlines:
        content = getattr(node, "content", None)
        if isinstance(content, str):
            out.append(content)
        elif hasattr(node, "inlines"):
            out.append(_text(node.inlines))
    return "".join(out)


# --- Item-level HTML block continuation (feed lines 756-783) ---------------
# The whole `if self.list_stack and ...items[-1].html_block_type is not None`
# seam was unexercised: no existing test put a MULTI-LINE HTML block inside a
# list item. An item HTML block opens with e.g. `- <div>` (handled in
# _add_content_line); these tests drive the per-line continuation logic that
# `feed` runs for the SUBSEQUENT lines.


def test_item_html_block_type6_continues_then_blank_closes():
    """`- <div>` opens a type-6 item HTML block; a following indented line
    continues it (arms 767 type-6, 776-778 append), a blank line closes it
    (768-770), and later content becomes a sibling paragraph in the item."""
    doc = parse("- <div>\n  more html\n\n  para after")
    assert len(doc.blocks) == 1
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    item_blocks = lst.items[0].blocks
    assert isinstance(item_blocks[0], HtmlBlock)
    assert item_blocks[0].raw == "<div>\nmore html\n"
    assert isinstance(item_blocks[1], Paragraph)
    assert _text(item_blocks[1].inlines) == "para after"


def test_item_html_block_type6_closed_by_sibling_marker():
    """A dedented sibling marker (`- next`) ends a type-6 item HTML block and
    the line is re-routed as a new sibling item (arms 773-775)."""
    doc = parse("- <div>\n  content\n- next item")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert len(lst.items) == 2
    assert isinstance(lst.items[0].blocks[0], HtmlBlock)
    assert lst.items[0].blocks[0].raw == "<div>\ncontent\n"
    assert _text(lst.items[1].blocks[0].inlines) == "next item"


def test_item_html_block_type1_closes_on_end_tag():
    """`- <script>` opens a type-1 item HTML block; the closing `</script>`
    line ends it (arms 779-783, _html_block_end_matches True), and later
    content is a sibling paragraph in the item."""
    doc = parse("- <script>\n  x=1\n  </script>\n  after")
    lst = doc.blocks[0]
    item_blocks = lst.items[0].blocks
    assert isinstance(item_blocks[0], HtmlBlock)
    assert item_blocks[0].raw == "<script>\nx=1\n</script>\n"
    assert isinstance(item_blocks[1], Paragraph)
    assert _text(item_blocks[1].inlines) == "after"


def test_item_html_block_type1_runs_to_eof_unclosed():
    """An unclosed type-1 item HTML block keeps appending lines (arm 780, the
    end-match-False path) until EOF flushes it."""
    doc = parse("- <script>\n  still open")
    lst = doc.blocks[0]
    block = lst.items[0].blocks[0]
    assert isinstance(block, HtmlBlock)
    assert block.raw == "<script>\nstill open\n"


# --- Indented-code blank line with >= 4 columns (feed line 799-800) --------


def test_indented_code_blank_line_preserves_indent_remainder():
    """A blank-but-spaces line with >= 4 leading columns inside an open
    document-level indented code block is buffered with its remainder past
    column 4 preserved (arm 799-800), then flushed when the block continues."""
    doc = parse("    code1\n        \n    code2")
    assert len(doc.blocks) == 1
    cb = doc.blocks[0]
    assert isinstance(cb, CodeBlock)
    # The 8-space blank line keeps 4 trailing spaces after the 4-col strip.
    assert cb.content == "code1\n    \ncode2\n"


# --- Table broken by a block-level opener (feed line 833-849) --------------


def test_table_closed_by_following_heading():
    """A line that is not a table row AND is a block-level opener (here an ATX
    heading) closes the open table and is re-handled (the 833 guard is False,
    so control reaches 849 _close_table)."""
    doc = parse("| a | b |\n|---|---|\n| 1 | 2 |\n# heading")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], Table)
    assert len(doc.blocks[0].rows) == 1
    assert isinstance(doc.blocks[1], Heading)
    assert doc.blocks[1].level == 1
    assert _text(doc.blocks[1].inlines) == "heading"


# --- Table delimiter / header cell-count mismatch (feed line 988-1001) -----


def test_table_header_delimiter_cell_count_mismatch_is_paragraph():
    """When the header row and delimiter row have different cell counts the
    construct is NOT a table and stays a paragraph (GFM example 203 shape;
    the 988 count-equality guard is False, so control skips table-open)."""
    doc = parse("| a | b |\n| - |")
    assert len(doc.blocks) == 1
    assert isinstance(doc.blocks[0], Paragraph)
    assert _text(doc.blocks[0].inlines) == "| a | b |\n| - |"


# --- Empty-item-then-blank cannot absorb content (feed lines 1023-1034) ----


def test_empty_item_followed_by_blank_cannot_absorb_content():
    """CommonMark example 280: `-` (empty item) then a blank then `  foo`.
    The empty item cannot absorb later content (arm 1023 item_is_empty &
    blank_before_next_item, 1030-1034 not-a-matching-marker break); `foo`
    becomes a top-level paragraph."""
    doc = parse("-\n\n  foo")
    assert len(doc.blocks) == 2
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert lst.items[0].blocks == ()
    assert isinstance(doc.blocks[1], Paragraph)
    assert _text(doc.blocks[1].inlines) == "foo"


def test_empty_item_followed_by_blank_then_sibling_marker_continues_list():
    """CommonMark example 315: `* a` / `*` (empty) / blank / `* c`. A sibling
    marker still continues the list even after the empty-item blank (arm 1030
    marker-matches, so the break is NOT taken)."""
    doc = parse("* a\n*\n\n* c")
    assert len(doc.blocks) == 1
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert len(lst.items) == 3
    assert _text(lst.items[0].blocks[0].inlines) == "a"
    assert lst.items[1].blocks == ()
    assert _text(lst.items[2].blocks[0].inlines) == "c"


# --- Thematic break wins over sibling marker (feed lines 1054-1075) --------


def test_thematic_break_wins_over_sibling_list_marker():
    """`- a` then `* * *` at the list's marker column: the thematic-break
    shape wins over a sibling list marker (arm 1063-1065), closing the list."""
    doc = parse("- a\n* * *")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], List)
    assert _text(doc.blocks[0].items[0].blocks[0].inlines) == "a"
    assert isinstance(doc.blocks[1], ThematicBreak)


# --- Lazy continuation into a nested item-blockquote (feed lines 1101-1113)-


def test_lazy_continuation_into_nested_item_blockquote():
    """`- > quote` then a bare `continued` line lazily continues the nested
    item-blockquote's paragraph (arms 1101 item.in_quote, 1111-1113 append),
    rather than ending the list."""
    doc = parse("- > quote para\ncontinued here")
    assert len(doc.blocks) == 1
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    bq = lst.items[0].blocks[0]
    assert isinstance(bq, BlockQuote)
    para = bq.blocks[0]
    assert isinstance(para, Paragraph)
    assert _text(para.inlines) == "quote para\ncontinued here"


def test_item_blockquote_not_lazily_continued_by_heading():
    """A non-paragraph line (ATX heading) does NOT lazily continue the nested
    item-blockquote (arm 1111 condition False, fall through to 1143); it
    breaks out and becomes a top-level heading."""
    doc = parse("- > quote\n# heading")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], List)
    bq = doc.blocks[0].items[0].blocks[0]
    assert isinstance(bq, BlockQuote)
    assert _text(bq.blocks[0].inlines) == "quote"
    assert isinstance(doc.blocks[1], Heading)


# --- Lazy continuation of an item's own paragraph (feed lines 1132-1134) ---


def test_lazy_continuation_of_item_paragraph():
    """`- aaa` then a bare unindented `bbb` lazily continues the item's own
    open paragraph (arm 1132 cur_para_shape, 1133 _add_paragraph_line)."""
    doc = parse("- aaa\nbbb")
    assert len(doc.blocks) == 1
    lst = doc.blocks[0]
    para = lst.items[0].blocks[0]
    assert isinstance(para, Paragraph)
    assert _text(para.inlines) == "aaa\nbbb"


def test_over_indented_marker_becomes_item_paragraph_text():
    """CommonMark example 312: a marker indented 4+ columns past the deepest
    list's parent content column is too deep to be a marker and becomes the
    item's paragraph text (arm 1128 over_indented_marker, 1132-1134)."""
    doc = parse("- a\n - b\n  - c\n   - d\n    - e")
    # Deepest item `d` absorbs `    - e` as the literal text "- e".
    para_texts = []

    def collect(blocks):
        for b in blocks:
            if isinstance(b, Paragraph):
                para_texts.append(_text(b.inlines))
            if isinstance(b, List):
                for it in b.items:
                    collect(it.blocks)

    collect(doc.blocks)
    assert "d\n- e" in para_texts


# --- Blank-loose propagation to outer item (feed lines 1150-1160) ----------


def test_blank_after_nested_list_makes_outer_item_loose():
    """CommonMark example 325: `* foo` / `  * bar` / blank / `  baz`. The
    blank that closed the nested list propagates loose-ness to the OUTER item
    (arm 1150 elif, 1156-1160 force_loose TRUE arm), and `baz` is a new
    paragraph in the outer item."""
    doc = parse("* foo\n  * bar\n\n  baz")
    outer = doc.blocks[0]
    assert isinstance(outer, List)
    assert outer.tight is False  # outer made loose by the propagated blank
    item_blocks = outer.items[0].blocks
    assert _text(item_blocks[0].inlines) == "foo"
    assert isinstance(item_blocks[1], List)
    assert isinstance(item_blocks[2], Paragraph)
    assert _text(item_blocks[2].inlines) == "baz"


def test_outer_continuation_closes_nested_list_without_pending_blank():
    """A heading at the outer item's content column closes a nested list with
    NO pending blank recorded (arm 1150 elif entered, but 1156 any() is False
    so force_loose is NOT set -> 1156-1163 FALSE arm). The heading stays a
    block of the outer item."""
    doc = parse("- a\n  - b\n  # h")
    outer = doc.blocks[0]
    assert isinstance(outer, List)
    item_blocks = outer.items[0].blocks
    assert _text(item_blocks[0].inlines) == "a"
    assert isinstance(item_blocks[1], List)  # the nested list, now closed
    assert _text(item_blocks[1].items[0].blocks[0].inlines) == "b"
    assert isinstance(item_blocks[2], Heading)
    assert item_blocks[2].level == 1
    assert _text(item_blocks[2].inlines) == "h"


# --- Tab-spanning dedent in kept list (feed lines 1190-1204) ---------------


def test_tab_spanning_content_boundary_in_item_dedent():
    """CommonMark Tabs example 5: `- foo` / blank / `\\t\\tbar`. The leading
    tabs span the item content boundary and are expanded before stripping
    (arm 1200-1202), yielding indented code `  bar` inside the item."""
    doc = parse("- foo\n\n\t\tbar")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    item_blocks = lst.items[0].blocks
    assert _text(item_blocks[0].inlines) == "foo"
    cb = item_blocks[1]
    assert isinstance(cb, CodeBlock)
    assert cb.content == "  bar\n"


def test_narrow_sibling_continuation_below_list_frozen_column():
    """A wide first marker (`10. `) freezes the list content column at 4, then
    a narrow sibling (`1. `) has content column 3. A line indented 3 continues
    the narrow item even though it is BELOW the list's frozen column, taking
    the dedent else-branch (arm 1190 False -> 1204 lstrip)."""
    doc = parse("10. a\n1. b\n   c")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert lst.ordered is True
    assert len(lst.items) == 2
    assert _text(lst.items[0].blocks[0].inlines) == "a"
    # `c` (indent 3) continues item `b` (content col 3 < list frozen col 4).
    assert _text(lst.items[1].blocks[0].inlines) == "b\nc"


# --- Indented code block inside a list item (feed lines 1214-1238) ---------


def test_item_indented_code_first_line_loose_then_continues_without_blank():
    """`- foo` / blank / `      code1` / `      code2`. The FIRST code line
    has a pending blank and forces the item loose (arm 1226-1228 TRUE arm);
    the SECOND code line continues the same block with no pending blank (arm
    1226 False -> 1229 FALSE arm). Both arms in one input."""
    doc = parse("- foo\n\n      code1\n      code2")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert lst.tight is False
    item_blocks = lst.items[0].blocks
    assert _text(item_blocks[0].inlines) == "foo"
    cb = item_blocks[1]
    assert isinstance(cb, CodeBlock)
    assert cb.content == "code1\ncode2\n"


def test_item_opens_directly_with_indented_code_no_pending_blank():
    """`-     code` opens an item that begins directly with an indented code
    block, with no pending blank (arm 1226 condition False -> 1229), so the
    item stays tight."""
    doc = parse("-     code")
    lst = doc.blocks[0]
    assert isinstance(lst, List)
    assert lst.tight is True
    cb = lst.items[0].blocks[0]
    assert isinstance(cb, CodeBlock)
    assert cb.content == "code\n"


def test_item_indented_code_flushes_buffered_blank():
    """`- foo` / blank / `      code1` / blank / `      code2`. The interior
    blank is buffered then flushed into the item code block (arm 1229-1231),
    preserving the blank line between the two code lines."""
    doc = parse("- foo\n\n      code1\n\n      code2")
    lst = doc.blocks[0]
    cb = lst.items[0].blocks[1]
    assert isinstance(cb, CodeBlock)
    assert cb.content == "code1\n\ncode2\n"


def test_item_indented_code_closed_by_dedented_content():
    """An open item indented-code block is closed by a non-indented content
    line (arm 1234-1238 _close_item_indented_code), which becomes a following
    paragraph in the item."""
    doc = parse("- foo\n\n      code\n  bar")
    lst = doc.blocks[0]
    item_blocks = lst.items[0].blocks
    assert _text(item_blocks[0].inlines) == "foo"
    assert isinstance(item_blocks[1], CodeBlock)
    assert item_blocks[1].content == "code\n"
    assert isinstance(item_blocks[2], Paragraph)
    assert _text(item_blocks[2].inlines) == "bar"


# --- Post-list-walk HTML block re-check (feed lines 1245-1264) -------------


def test_html_block_after_list_is_recognized():
    """CommonMark Lists 308/309 shape: a list, a blank, then a type-6 HTML
    block. The list-stack walk closes the list, and the post-walk re-check
    opens the HTML block (arms 1256-1259, 1260 FALSE for type 6) instead of
    mis-parsing it as a paragraph."""
    doc = parse("- foo\n\n<div>\nbar\n</div>")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], List)
    assert _text(doc.blocks[0].items[0].blocks[0].inlines) == "foo"
    assert isinstance(doc.blocks[1], HtmlBlock)
    assert doc.blocks[1].raw == "<div>\nbar\n</div>\n"


def test_html_block_after_list_closes_on_same_line():
    """A type-1 HTML block (`<pre>...</pre>`) after a list opens AND closes on
    the same line via the post-walk re-check (arm 1260-1263 TRUE: start_type in
    1-5 and end matches). `after` lands as a separate paragraph, proving the
    block was closed rather than left open."""
    doc = parse("- foo\n\n<pre>code</pre>\nafter")
    assert len(doc.blocks) == 3
    assert isinstance(doc.blocks[0], List)
    assert isinstance(doc.blocks[1], HtmlBlock)
    assert doc.blocks[1].raw == "<pre>code</pre>\n"
    assert isinstance(doc.blocks[2], Paragraph)
    assert _text(doc.blocks[2].inlines) == "after"


# --- Post-list-walk indented-code re-check (feed lines 1272-1280) ----------


def test_indented_code_after_list_is_recognized():
    """CommonMark Lists example 313: `1. a` / blank / `  2. b` / blank /
    `    3. c`. The final over-indented line closes the list and is
    recognised as a document-level indented code block by the post-walk
    re-check (arm 1272-1280) rather than a paragraph."""
    doc = parse("1. a\n\n  2. b\n\n    3. c")
    assert isinstance(doc.blocks[0], List)
    cb = doc.blocks[-1]
    assert isinstance(cb, CodeBlock)
    assert cb.content == "3. c\n"
