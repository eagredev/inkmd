"""Block-level raw HTML passthrough tests (CommonMark §4.6).

The parser recognises the seven HTML-block start conditions and emits an
HtmlBlock AST node holding the literal source lines verbatim. The
conformance serialiser emits those bytes unchanged; the PDF renderer has
no HTML engine, so a block degrades to its extracted text content
(script/style/comment bodies dropped, other tag syntax stripped).

References:
    - https://spec.commonmark.org/0.31.2/#html-blocks
    - src/inkmd/parser.py (_html_block_start_type, _BlockParser)
"""

from __future__ import annotations

import inkmd
from inkmd.ast import HtmlBlock, Paragraph
from inkmd.parser import parse
from inkmd.render import _html_block_to_text


def _blocks(md: str):
    return parse(md).blocks


def test_type6_div_block_then_blank_ends():
    blocks = _blocks("<div>\nbar\n</div>\n\nafter\n")
    assert isinstance(blocks[0], HtmlBlock)
    assert blocks[0].raw == "<div>\nbar\n</div>\n"
    assert isinstance(blocks[1], Paragraph)


def test_type2_comment_closer_included():
    blocks = _blocks("<!-- a\ncomment -->\nokay\n")
    assert isinstance(blocks[0], HtmlBlock)
    assert blocks[0].raw == "<!-- a\ncomment -->\n"
    assert isinstance(blocks[1], Paragraph)


def test_type1_script_runs_to_close_tag():
    md = "<script>\nfoo\n</script>\nokay\n"
    blocks = _blocks(md)
    assert isinstance(blocks[0], HtmlBlock)
    assert blocks[0].raw == "<script>\nfoo\n</script>\n"
    assert isinstance(blocks[1], Paragraph)


def test_type1_closer_keeps_trailing_content():
    # CommonMark example 178: content after </script> stays in the block.
    blocks = _blocks("<script>\nfoo\n</script>1. *bar*\n")
    assert isinstance(blocks[0], HtmlBlock)
    assert blocks[0].raw == "<script>\nfoo\n</script>1. *bar*\n"
    assert len(blocks) == 1


def test_type7_cannot_interrupt_paragraph():
    # A type-7 start after open paragraph text is lazy continuation.
    blocks = _blocks('Foo\n<a href="bar">\nbaz\n')
    assert isinstance(blocks[0], Paragraph)
    assert all(not isinstance(b, HtmlBlock) for b in blocks)


def test_type6_can_interrupt_paragraph():
    blocks = _blocks("Foo\n<div>\nbar\n</div>\n")
    assert isinstance(blocks[0], Paragraph)
    assert isinstance(blocks[1], HtmlBlock)


def test_four_space_indent_is_code_not_html():
    blocks = _blocks("    <!-- foo -->\n")
    # 4-space indent makes it an indented code block, not an HTML block.
    assert not any(isinstance(b, HtmlBlock) for b in blocks)


def test_no_inline_processing_inside_block():
    blocks = _blocks("<div>\n*foo*\n</div>\n")
    assert isinstance(blocks[0], HtmlBlock)
    # The emphasis is preserved verbatim, not parsed.
    assert "*foo*" in blocks[0].raw


def test_html_disabled_keeps_text():
    doc = parse("<div>\nbar\n</div>\n", html=False)
    assert not any(isinstance(b, HtmlBlock) for b in doc.blocks)


def test_render_extracts_div_text():
    text = _html_block_to_text("<div>\n  <span>hello world</span>\n</div>\n")
    assert text == "hello world"


def test_render_drops_script_body():
    text = _html_block_to_text("<script>\nalert(1);\n</script>\n")
    assert text == ""


def test_render_drops_comment():
    text = _html_block_to_text("<!-- nothing to see -->\n")
    assert text == ""


def test_render_extracts_table_text():
    text = _html_block_to_text("<table>\n<tr><td>cell</td></tr>\n</table>\n")
    assert text == "cell"


def test_compile_does_not_crash_on_html_block():
    md = (
        "# Title\n\n"
        '<div align="center">\n'
        "<strong>Project</strong>\n"
        "</div>\n\n"
        "<!-- comment -->\n\n"
        "<table><tr><td>x</td></tr></table>\n\n"
        "End.\n"
    )
    pdf = inkmd.compile(md)
    assert pdf.startswith(b"%PDF-")
