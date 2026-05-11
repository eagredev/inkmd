"""render_document tests — milestone 0.0.4+."""

from __future__ import annotations

import pytest

from inkmd.ast import Code, Document, Emphasis, Paragraph, Strong, Text
from inkmd.layout import Run
from inkmd.render import (
    BODY_FONT,
    BODY_SIZE,
    HELVETICA_FAMILY,
    TIMES_FAMILY,
    render_document,
)


def test_empty_document_renders_empty_list():
    assert render_document(Document(blocks=())) == []


def test_single_paragraph_one_run():
    doc = Document(blocks=(Paragraph(inlines=(Text("Hello."),)),))
    out = render_document(doc)
    assert len(out) == 1
    assert out[0].runs == (Run(text="Hello.", font=BODY_FONT, size=BODY_SIZE),)


def test_multiple_paragraphs_produce_separate_run_lists():
    doc = Document(blocks=(
        Paragraph(inlines=(Text("One."),)),
        Paragraph(inlines=(Text("Two."),)),
    ))
    out = render_document(doc)
    assert len(out) == 2
    assert out[0].runs[0].text == "One."
    assert out[1].runs[0].text == "Two."


def test_runs_use_body_font_and_size():
    doc = Document(blocks=(Paragraph(inlines=(Text("Body."),)),))
    run = render_document(doc)[0].runs[0]
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


# --- Inline rendering (0.0.5) ---------------------------------------------


def _para(*inlines):
    return Document(blocks=(Paragraph(inlines=tuple(inlines)),))


def test_strong_renders_in_bold_face():
    doc = _para(Strong(inlines=(Text("bold"),)))
    runs = render_document(doc)[0].runs
    assert runs == (Run(text="bold", font=HELVETICA_FAMILY.bold, size=BODY_SIZE),)


def test_emphasis_renders_in_italic_face():
    doc = _para(Emphasis(inlines=(Text("italic"),)))
    runs = render_document(doc)[0].runs
    assert runs == (Run(text="italic", font=HELVETICA_FAMILY.italic, size=BODY_SIZE),)


def test_code_renders_in_monospace_face():
    doc = _para(Code(content="print"))
    runs = render_document(doc)[0].runs
    assert runs == (Run(text="print", font=HELVETICA_FAMILY.monospace, size=BODY_SIZE),)


def test_mixed_inlines_produce_multiple_runs():
    doc = _para(
        Text("a "),
        Strong(inlines=(Text("b"),)),
        Text(" c "),
        Emphasis(inlines=(Text("d"),)),
        Text(" e "),
        Code(content="f"),
    )
    runs = render_document(doc)[0].runs
    fonts = [r.font for r in runs]
    assert fonts == [
        HELVETICA_FAMILY.regular,
        HELVETICA_FAMILY.bold,
        HELVETICA_FAMILY.regular,
        HELVETICA_FAMILY.italic,
        HELVETICA_FAMILY.regular,
        HELVETICA_FAMILY.monospace,
    ]


def test_strong_within_emphasis_uses_bold_italic():
    """Strong inside Emphasis should pick the family's bold_italic face."""
    doc = _para(Emphasis(inlines=(
        Text("emph "),
        Strong(inlines=(Text("inner"),)),
    )))
    runs = render_document(doc)[0].runs
    assert runs[0].font == HELVETICA_FAMILY.italic
    assert runs[1].font == HELVETICA_FAMILY.bold_italic


def test_emphasis_within_strong_uses_bold_italic():
    doc = _para(Strong(inlines=(
        Text("strong "),
        Emphasis(inlines=(Text("inner"),)),
    )))
    runs = render_document(doc)[0].runs
    assert runs[0].font == HELVETICA_FAMILY.bold
    assert runs[1].font == HELVETICA_FAMILY.bold_italic


def test_times_family_routes_to_times_fonts():
    """When the family is Times, Strong → Times-Bold etc."""
    doc = _para(Strong(inlines=(Text("bold"),)))
    runs = render_document(doc, family=TIMES_FAMILY)[0].runs
    assert runs[0].font == "Times-Bold"


def test_emphasis_in_times_family():
    doc = _para(Emphasis(inlines=(Text("ital"),)))
    runs = render_document(doc, family=TIMES_FAMILY)[0].runs
    assert runs[0].font == "Times-Italic"


def test_code_in_times_family_uses_courier():
    """Code spans always use Courier regardless of body family."""
    doc = _para(Code(content="ls"))
    runs = render_document(doc, family=TIMES_FAMILY)[0].runs
    assert runs[0].font == "Courier"
