"""Reference-style link and image tests (CommonMark sections 4.7 + 6.3).

Three reference forms resolve against a per-document table of
``[label]: url "title"`` definitions:

    [link text][label]   — full reference
    [label][]            — collapsed reference (text === label)
    [label]              — shortcut reference (no second brackets)

Image variants mirror with a leading ``!``. Labels are normalised
(Unicode case-fold, surrounding whitespace stripped, internal
whitespace collapsed). Resolution is document-scoped: a reference
earlier in the source can resolve a definition later in the source.
Unresolved references fall back to literal source text.
"""

from __future__ import annotations

import re

import inkmd
from inkmd.ast import Emphasis, Image, Link, Text
from inkmd.parser import parse


# --- Definition scanning -------------------------------------------------


def test_definition_consumed_no_paragraph():
    doc = parse('[foo]: https://example.com "title"\n')
    assert doc.blocks == ()
    assert doc.link_references == (("foo", "https://example.com", "title"),)


def test_definition_without_title():
    doc = parse('[foo]: https://example.com\n')
    assert doc.link_references == (("foo", "https://example.com", ""),)


def test_definition_with_paren_title():
    doc = parse('[foo]: https://example.com (a title)\n')
    assert doc.link_references == (("foo", "https://example.com", "a title"),)


def test_definition_with_single_quote_title():
    doc = parse("[foo]: https://example.com 'a title'\n")
    assert doc.link_references == (("foo", "https://example.com", "a title"),)


def test_multiple_definitions_first_wins():
    src = "[foo]: https://first.example\n[foo]: https://second.example\n"
    doc = parse(src)
    table = doc.link_reference_table()
    assert table["foo"] == ("https://first.example", "")


def test_indented_4_spaces_is_not_a_definition():
    """4-space indent makes it an indented code block context, not a def."""
    doc = parse("    [foo]: /url\n\n[foo]\n")
    assert doc.link_references == ()


def test_definition_inside_code_fence_ignored():
    src = "```\n[foo]: /url\n```\n\n[foo]\n"
    doc = parse(src)
    assert doc.link_references == ()


def test_definition_after_heading():
    """ATX heading closes any open paragraph; next line can start a def."""
    doc = parse("# Heading\n[foo]: /url\n")
    assert doc.link_references == (("foo", "/url", ""),)


# --- Label normalisation -------------------------------------------------


def test_label_case_insensitive():
    doc = parse("[FOO]: /url\n\n[foo]")
    assert doc.blocks[0].inlines[0] == Link(
        inlines=(Text("foo"),), url="/url", title=""
    )


def test_label_whitespace_collapsed():
    doc = parse("[foo   bar]: /url\n\n[foo bar]")
    link = doc.blocks[0].inlines[0]
    assert isinstance(link, Link)
    assert link.url == "/url"


def test_label_unicode_casefold():
    """Greek capital sigma matches lowercase sigma."""
    doc = parse("[Σ]: /url\n\n[σ]")
    link = doc.blocks[0].inlines[0]
    assert isinstance(link, Link)
    assert link.url == "/url"


# --- Full reference form -------------------------------------------------


def test_full_reference_link():
    doc = parse("[foo]: /url\n\n[click here][foo]")
    assert doc.blocks[0].inlines == (
        Link(inlines=(Text("click here"),), url="/url", title=""),
    )


def test_full_reference_with_title():
    doc = parse('[foo]: /url "hover"\n\n[click][foo]')
    link = doc.blocks[0].inlines[0]
    assert link.title == "hover"


def test_full_reference_inline_text_parsed():
    """Visible text inside [text] should parse emphasis/code/etc."""
    doc = parse("[foo]: /url\n\n[*bold*][foo]")
    link = doc.blocks[0].inlines[0]
    assert isinstance(link, Link)
    assert link.inlines == (Emphasis(inlines=(Text("bold"),)),)


# --- Collapsed reference form --------------------------------------------


def test_collapsed_reference():
    doc = parse("[foo]: /url\n\n[foo][]")
    assert doc.blocks[0].inlines == (
        Link(inlines=(Text("foo"),), url="/url", title=""),
    )


# --- Shortcut reference form ---------------------------------------------


def test_shortcut_reference():
    doc = parse("[foo]: /url\n\n[foo]")
    assert doc.blocks[0].inlines == (
        Link(inlines=(Text("foo"),), url="/url", title=""),
    )


def test_shortcut_inside_emphasis():
    doc = parse("[foo]: /url\n\n*[foo]* end")
    inlines = doc.blocks[0].inlines
    assert inlines[0] == Emphasis(
        inlines=(Link(inlines=(Text("foo"),), url="/url", title=""),)
    )


# --- Forward references --------------------------------------------------


def test_definition_after_use_resolves():
    """A reference earlier in the source resolves to a later definition."""
    doc = parse("Use [foo] here.\n\n[foo]: /url\n")
    text_nodes = doc.blocks[0].inlines
    assert any(isinstance(n, Link) and n.url == "/url" for n in text_nodes)


# --- Image reference forms -----------------------------------------------


def test_full_image_reference():
    doc = parse("[logo]: img.png\n\n![alt][logo]")
    assert doc.blocks[0].inlines == (
        Image(inlines=(Text("alt"),), url="img.png", title=""),
    )


def test_collapsed_image_reference():
    doc = parse("[logo]: img.png\n\n![logo][]")
    img = doc.blocks[0].inlines[0]
    assert isinstance(img, Image)
    assert img.url == "img.png"


def test_shortcut_image_reference():
    doc = parse("[logo]: img.png\n\n![logo]")
    img = doc.blocks[0].inlines[0]
    assert isinstance(img, Image)
    assert img.url == "img.png"


# --- Precedence with inline form -----------------------------------------


def test_inline_link_wins_over_reference():
    doc = parse("[foo]: /ref\n\n[foo](/inline)")
    link = doc.blocks[0].inlines[0]
    assert isinstance(link, Link)
    assert link.url == "/inline"


# --- Unresolved fallback -------------------------------------------------


def test_unresolved_shortcut_renders_literal():
    doc = parse("[nothing]")
    inlines = doc.blocks[0].inlines
    assert not any(isinstance(n, Link) for n in inlines)
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "[nothing]" in text


def test_unresolved_full_form_renders_literal():
    doc = parse("[text][nothing]")
    inlines = doc.blocks[0].inlines
    assert not any(isinstance(n, Link) for n in inlines)


# --- End-to-end PDF ------------------------------------------------------


def test_reference_link_produces_uri_annotation():
    pdf = inkmd.compile("[foo]: https://example.com\n\n[foo]")
    assert re.search(rb"/URI\s*\(https://example\.com\)", pdf), \
        "Expected /URI annotation for resolved reference link"


def test_reference_image_produces_alt_fallback():
    """Missing image source should fall back to italic alt text, not crash."""
    pdf = inkmd.compile("[missing]: not-a-real-file.png\n\n![see this][missing]")
    assert pdf.startswith(b"%PDF-")
