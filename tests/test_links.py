"""Link parser + render tests — milestone 0.0.11.

Covers inline links ``[text](url)``, autolinks ``<url>``, and the PDF
emission path that produces both visible blue+underlined runs and
clickable ``/Link`` annotations.
"""

from __future__ import annotations

import inkmd
from inkmd.ast import (
    AutoLink,
    Emphasis,
    Link,
    Paragraph,
    Strong,
    Text,
)
from inkmd.parser import parse


# --- Parser: inline links --------------------------------------------------


def test_simple_inline_link():
    doc = parse("[click](https://example.com)")
    p = doc.blocks[0]
    assert p.inlines == (Link(inlines=(Text("click"),), url="https://example.com", title=""),)


def test_link_text_can_contain_emphasis():
    doc = parse("[**bold** text](https://example.com)")
    p = doc.blocks[0]
    link = p.inlines[0]
    assert isinstance(link, Link)
    assert link.inlines == (
        Strong(inlines=(Text("bold"),)),
        Text(" text"),
    )


def test_link_with_title():
    doc = parse('[name](https://example.com "Tooltip")')
    p = doc.blocks[0]
    assert p.inlines == (Link(inlines=(Text("name"),), url="https://example.com", title="Tooltip"),)


def test_link_with_single_quote_title():
    doc = parse("[name](https://example.com 'Tooltip')")
    p = doc.blocks[0]
    assert p.inlines[0].title == "Tooltip"


def test_link_inline_with_surrounding_text():
    doc = parse("Visit [home](https://example.com) today.")
    p = doc.blocks[0]
    assert len(p.inlines) == 3
    assert isinstance(p.inlines[1], Link)


def test_two_links_in_one_paragraph():
    doc = parse("[a](https://a.com) and [b](https://b.com)")
    p = doc.blocks[0]
    links = [inl for inl in p.inlines if isinstance(inl, Link)]
    assert len(links) == 2
    assert links[0].url == "https://a.com"
    assert links[1].url == "https://b.com"


def test_url_with_special_chars_preserved():
    doc = parse("[q](https://example.com/path?a=1&b=2#frag)")
    p = doc.blocks[0]
    assert p.inlines[0].url == "https://example.com/path?a=1&b=2#frag"


def test_angle_bracket_url_form():
    doc = parse("[name](<https://example.com>)")
    p = doc.blocks[0]
    assert p.inlines[0].url == "https://example.com"


# --- Parser: malformed / falsy cases --------------------------------------


def test_bracket_text_without_paren_is_literal():
    doc = parse("Just [text] here.")
    p = doc.blocks[0]
    # Falls back to literal text.
    assert p.inlines == (Text("Just [text] here."),)


def test_unmatched_opening_bracket_is_literal():
    doc = parse("Open [bracket forever.")
    p = doc.blocks[0]
    assert p.inlines == (Text("Open [bracket forever."),)


def test_link_with_nested_bracket_in_text_bails():
    """v0.1 doesn't support nested brackets in link text."""
    doc = parse("[outer [inner] text](https://example.com)")
    # We expect this to fall back to literal — no Link node.
    p = doc.blocks[0]
    assert not any(isinstance(i, Link) for i in p.inlines)


# --- Parser: autolinks ----------------------------------------------------


def test_autolink_url():
    doc = parse("<https://example.com>")
    p = doc.blocks[0]
    assert p.inlines == (AutoLink(url="https://example.com"),)


def test_autolink_email_gets_mailto_prefix():
    doc = parse("<dylan@example.com>")
    p = doc.blocks[0]
    assert p.inlines == (AutoLink(url="mailto:dylan@example.com"),)


def test_autolink_with_path_and_query():
    doc = parse("<https://example.com/foo?bar=baz>")
    p = doc.blocks[0]
    assert p.inlines == (AutoLink(url="https://example.com/foo?bar=baz"),)


def test_autolink_with_internal_space_is_not_a_link():
    """A URL with spaces is not a valid autolink."""
    doc = parse("<https://example.com with space>")
    p = doc.blocks[0]
    assert not any(isinstance(i, AutoLink) for i in p.inlines)


def test_autolink_without_scheme_is_not_a_link():
    """Plain text inside angle brackets without a scheme is not an autolink."""
    doc = parse("<just text>")
    p = doc.blocks[0]
    assert not any(isinstance(i, AutoLink) for i in p.inlines)


# --- Render ---------------------------------------------------------------


def test_render_link_runs_have_blue_color():
    from inkmd.render import LINK_COLOR, render_document

    doc = parse("[click](https://example.com)")
    block = render_document(doc)[0]
    runs = block.runs
    assert all(r.color == LINK_COLOR for r in runs if r.text)


def test_render_link_runs_carry_url():
    from inkmd.render import render_document

    doc = parse("[click](https://example.com)")
    block = render_document(doc)[0]
    runs = block.runs
    assert all(r.link_url == "https://example.com" for r in runs if r.text)


def test_render_autolink_url_is_both_text_and_target():
    from inkmd.render import render_document

    doc = parse("<https://example.com>")
    block = render_document(doc)[0]
    runs = block.runs
    assert runs[0].text == "https://example.com"
    assert runs[0].link_url == "https://example.com"


def test_render_link_with_inner_emphasis_keeps_link_url():
    """A Strong inside a Link still inherits the link URL."""
    from inkmd.render import render_document

    doc = parse("[**bold** text](https://example.com)")
    block = render_document(doc)[0]
    for r in block.runs:
        if r.text:
            assert r.link_url == "https://example.com", f"run {r.text!r} missing url"


# --- End-to-end -----------------------------------------------------------


def test_compile_link_produces_valid_pdf():
    out = inkmd.compile("[click](https://example.com)")
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_compile_link_emits_annotation_object():
    """The PDF must contain a /Subtype /Link annotation."""
    out = inkmd.compile("[click](https://example.com)")
    assert b"/Subtype /Link" in out


def test_compile_link_includes_uri_action():
    """The annotation must reference the URL via /A /URI."""
    out = inkmd.compile("[click](https://example.com)")
    assert b"/S /URI" in out
    assert b"https://example.com" in out


def test_compile_link_page_has_annots_array():
    """The Page object must have an /Annots array referencing the link."""
    out = inkmd.compile("[click](https://example.com)")
    assert b"/Annots [" in out


def test_compile_link_emits_blue_text_color():
    """The visible link text must have an /rg colour operator other than 0 0 0."""
    out = inkmd.compile("[click](https://example.com)")
    # The link colour is (0, 0.2, 0.8) → renders as "0 .2 .8 rg" (after _fmt).
    assert b"0 .2 .8 rg" in out or b"0 0.2 0.8 rg" in out


def test_compile_link_emits_underline_rectangle():
    """The underline appears as a re/f shape — the file should contain re f."""
    out = inkmd.compile("[click](https://example.com)")
    # The underline is one of many `re f` shapes; just check the operator is present.
    assert b" re f" in out


def test_compile_two_links_emit_two_annotations():
    """Two separate links must yield two Annot objects."""
    md = "[a](https://a.com) and [b](https://b.com)"
    out = inkmd.compile(md)
    assert out.count(b"/Subtype /Link") == 2


def test_compile_autolink_emits_annotation():
    out = inkmd.compile("<https://example.com>")
    assert b"/Subtype /Link" in out
    assert b"https://example.com" in out


def test_compile_email_autolink_uses_mailto():
    out = inkmd.compile("<dylan@example.com>")
    assert b"mailto:dylan@example.com" in out


def test_compile_link_in_list():
    out = inkmd.compile("- [click](https://example.com)\n- second item")
    assert b"/Subtype /Link" in out
    assert b"https://example.com" in out


def test_compile_link_in_blockquote():
    out = inkmd.compile("> A [link](https://example.com).")
    assert b"/Subtype /Link" in out


def test_compile_link_in_table_cell():
    md = "| A | B |\n| --- | --- |\n| [home](https://example.com) | x |"
    out = inkmd.compile(md)
    assert b"/Subtype /Link" in out
    assert b"https://example.com" in out
