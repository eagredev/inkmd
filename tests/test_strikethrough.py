"""GFM strikethrough — milestone 0.0.12 (deferred-work #14).

Recognises ``~~text~~`` per GFM § "Strikethrough (extension)".
"""

from __future__ import annotations

import inkmd
from inkmd.ast import (
    Document,
    Emphasis,
    Paragraph,
    Strikethrough,
    Strong,
    Text,
)
from inkmd.parser import parse


# --- Parsing ---------------------------------------------------------------


def test_basic_strikethrough():
    doc = parse("~~struck~~")
    assert doc == Document(blocks=(
        Paragraph(inlines=(Strikethrough(inlines=(Text("struck"),)),)),
    ))


def test_strikethrough_inside_paragraph():
    doc = parse("before ~~middle~~ after")
    para = doc.blocks[0]
    assert para.inlines == (
        Text("before "),
        Strikethrough(inlines=(Text("middle"),)),
        Text(" after"),
    )


def test_single_tilde_strikes():
    """A single ~text~ pair produces a Strikethrough per GFM. The spec's
    text says "two tildes" but the reference implementation (cmark-gfm)
    accepts one or two; we follow the implementation, as does GitHub."""
    doc = parse("a ~tilde~ pair")
    para = doc.blocks[0]
    strikes = [x for x in para.inlines if isinstance(x, Strikethrough)]
    assert len(strikes) == 1
    inner_text = "".join(
        t.content for t in strikes[0].inlines if isinstance(t, Text)
    )
    assert inner_text == "tilde"


def test_unmatched_lone_tilde_stays_literal():
    """A single ~ with nothing to close it remains plain text."""
    doc = parse("alone ~ here")
    para = doc.blocks[0]
    text_content = "".join(t.content for t in para.inlines if isinstance(t, Text))
    assert "~" in text_content
    assert not any(isinstance(x, Strikethrough) for x in para.inlines)


def test_triple_tilde_inline_is_literal():
    """Three tildes inline (not at column 0) are not strikethrough.

    Note: ``~~~`` at the start of a line opens a tilde fenced code block
    (CommonMark/GFM), so we anchor this test inside a paragraph.
    """
    doc = parse("inline ~~~triple~~~ marker")
    para = doc.blocks[0]
    assert not any(isinstance(x, Strikethrough) for x in para.inlines)


def test_strike_nested_inside_strong():
    """``**~~x~~**`` → Strong containing Strikethrough."""
    doc = parse("**~~x~~**")
    para = doc.blocks[0]
    assert para.inlines == (
        Strong(inlines=(Strikethrough(inlines=(Text("x"),)),)),
    )


def test_strong_nested_inside_strike():
    """``~~**x**~~`` → Strikethrough containing Strong."""
    doc = parse("~~**x**~~")
    para = doc.blocks[0]
    assert para.inlines == (
        Strikethrough(inlines=(Strong(inlines=(Text("x"),)),)),
    )


def test_emphasis_nested_inside_strike():
    doc = parse("~~*x*~~")
    para = doc.blocks[0]
    assert para.inlines == (
        Strikethrough(inlines=(Emphasis(inlines=(Text("x"),)),)),
    )


def test_unpaired_opener_is_literal():
    """``~~no closer`` keeps the tildes as text — no AST node."""
    doc = parse("~~no closer")
    para = doc.blocks[0]
    assert not any(isinstance(x, Strikethrough) for x in para.inlines)


def test_strike_does_not_cross_paragraph_break():
    doc = parse("~~open\n\nclose~~")
    # Two paragraphs, neither containing a Strikethrough.
    assert len(doc.blocks) == 2
    for block in doc.blocks:
        if isinstance(block, Paragraph):
            assert not any(
                isinstance(x, Strikethrough) for x in block.inlines
            )


# --- Render & layout ------------------------------------------------------


def test_struck_runs_carry_strike_flag():
    """The render layer marks each Run inside a Strikethrough with strike=True."""
    from inkmd.render import render_document

    doc = parse("a ~~b~~ c")
    block = render_document(doc)[0]
    struck = [r for r in block.runs if r.strike]
    plain = [r for r in block.runs if not r.strike]
    assert len(struck) == 1
    assert struck[0].text == "b"
    # The leading "a " and trailing " c" are plain.
    assert any(r.text == "a " for r in plain)
    assert any(r.text == " c" for r in plain)


def test_strike_flag_propagates_through_strong():
    """A Strong inside a Strikethrough must still mark its runs struck."""
    from inkmd.render import render_document

    doc = parse("~~**bold**~~")
    block = render_document(doc)[0]
    assert any(r.strike for r in block.runs)
    # And the font should be bold for the inner run.
    bold_runs = [r for r in block.runs if r.strike]
    assert all("Bold" in r.font for r in bold_runs)


def test_layout_emits_strike_shape():
    """paginate_runs emits one Rect per contiguous struck region."""
    from inkmd.layout import paginate_runs
    from inkmd.render import render_document

    doc = parse("plain ~~struck~~ text")
    blocks = render_document(doc)
    pages = paginate_runs(blocks, page_width=612, page_height=792)
    assert len(pages[0].shapes) == 1
    sh = pages[0].shapes[0]
    # The strike rect should be roughly the width of 'struck' (~32pt at 12pt
    # Helvetica) and very thin.
    assert 25.0 < sh.width < 45.0
    assert sh.height < 1.5


def test_two_separate_strikes_emit_two_shapes():
    from inkmd.layout import paginate_runs
    from inkmd.render import render_document

    doc = parse("~~one~~ middle ~~two~~")
    blocks = render_document(doc)
    pages = paginate_runs(blocks, page_width=612, page_height=792)
    assert len(pages[0].shapes) == 2


# --- End-to-end PDF -------------------------------------------------------


def test_compile_strike_produces_valid_pdf():
    out = inkmd.compile("a ~~struck~~ word")
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_compile_strike_emits_rect_in_stream():
    """The horizontal-bar rectangle should appear as a ``re f`` shape pair."""
    out = inkmd.compile("a ~~struck~~ word")
    assert b" re f" in out


def test_compile_no_strike_emits_no_strike_rect():
    """Sanity: a paragraph without strikethrough produces no ``re f`` pairs
    (other than ones from links, code blocks, etc — which this paragraph has none of)."""
    out = inkmd.compile("a plain word with no decorations")
    assert b" re f" not in out


def test_strike_renders_in_table_cell():
    """Strikethrough must work inside table cells too."""
    md = (
        "| Header |\n"
        "| ------ |\n"
        "| ~~struck cell~~ |\n"
    )
    out = inkmd.compile(md)
    # Table emits grid `re f` shapes, so a precise count is awkward.
    # Just confirm it doesn't blow up and the PDF is valid.
    assert out.startswith(b"%PDF-1.4\n")
    assert b" re f" in out
