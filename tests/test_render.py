"""render_document tests — milestone 0.0.4: AST → Run lists."""

from __future__ import annotations

import pytest

from inkmd.ast import Document, Paragraph, Text
from inkmd.layout import Run
from inkmd.render import BODY_FONT, BODY_SIZE, render_document


def test_empty_document_renders_empty_list():
    assert render_document(Document(blocks=())) == []


def test_single_paragraph_one_run():
    doc = Document(blocks=(Paragraph(inlines=(Text("Hello."),)),))
    out = render_document(doc)
    assert out == [[Run(text="Hello.", font=BODY_FONT, size=BODY_SIZE)]]


def test_multiple_paragraphs_produce_separate_run_lists():
    doc = Document(blocks=(
        Paragraph(inlines=(Text("One."),)),
        Paragraph(inlines=(Text("Two."),)),
    ))
    out = render_document(doc)
    assert len(out) == 2
    assert out[0][0].text == "One."
    assert out[1][0].text == "Two."


def test_runs_use_body_font_and_size():
    doc = Document(blocks=(Paragraph(inlines=(Text("Body."),)),))
    run = render_document(doc)[0][0]
    assert run.font == BODY_FONT
    assert run.size == BODY_SIZE


def test_unsupported_block_raises():
    """Future block types not yet supported must fail loud, not silent."""
    class FakeBlock:
        pass
    doc = Document.__new__(Document)
    object.__setattr__(doc, "blocks", (FakeBlock(),))
    with pytest.raises(NotImplementedError):
        render_document(doc)
