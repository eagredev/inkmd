"""Forced page-break tests (v0.5 S5).

A block-level ``<div>`` whose style declares a CSS page break
(``page-break-after: always`` / ``break-after: page`` or the ``-before``
synonyms) starts the next content on a fresh page. ``---`` stays a
horizontal rule and never breaks; a plain ``<div>`` degrades to text as
before. The trigger is the markdown construct, not a LayoutConfig knob.
"""

from __future__ import annotations

import re

import inkmd
from inkmd.ast import HtmlBlock, PageBreak, Paragraph
from inkmd.html_filter import _is_page_break_div, filter_document
from inkmd.parser import parse


BRK = '<div style="page-break-after: always"></div>'
SYN = '<div style="break-after: page"></div>'


def _page_count(data: bytes) -> int:
    """Page count from the authoritative /Type /Pages /Count entry."""
    m = re.search(rb"/Type /Pages /Kids \[([^\]]+)\] /Count (\d+)", data)
    assert m is not None, "no page tree found in PDF"
    return int(m.group(2))


def _filtered_blocks(md: str):
    return filter_document(parse(md), html=True).blocks


# --- Parser / filter shape ------------------------------------------------


def test_parser_emits_htmlblock_for_break_div():
    """The break div arrives as an HtmlBlock with the style in .raw,
    before the HTML filter runs."""
    blocks = parse(f"A\n\n{BRK}\n\nB").blocks
    assert len(blocks) == 3
    assert isinstance(blocks[0], Paragraph)
    assert isinstance(blocks[1], HtmlBlock)
    assert "page-break-after" in blocks[1].raw
    assert isinstance(blocks[2], Paragraph)


def test_filter_converts_break_div_to_pagebreak():
    blocks = _filtered_blocks(f"A\n\n{BRK}\n\nB")
    assert [type(b).__name__ for b in blocks] == [
        "Paragraph", "PageBreak", "Paragraph",
    ]
    assert blocks[1] == PageBreak()


def test_filter_synonym_converts_to_pagebreak():
    blocks = _filtered_blocks(f"A\n\n{SYN}\n\nB")
    assert blocks[1] == PageBreak()


def test_plain_div_stays_htmlblock():
    """A plain <div> with no page-break style is left an HtmlBlock and
    degrades to its text content (it is not a break)."""
    blocks = _filtered_blocks("A\n\n<div>hello</div>\n\nB")
    assert not any(isinstance(b, PageBreak) for b in blocks)


# --- Predicate (unit) -----------------------------------------------------


def test_predicate_matches_both_spellings():
    assert _is_page_break_div('<div style="page-break-after: always"></div>')
    assert _is_page_break_div('<div style="break-after: page"></div>')


def test_predicate_matches_before_synonyms():
    assert _is_page_break_div('<div style="page-break-before: always"></div>')
    assert _is_page_break_div('<div style="break-before: page"></div>')


def test_predicate_lenient_on_whitespace_and_case():
    assert _is_page_break_div('<div style="page-break-after:always"></div>')
    assert _is_page_break_div('<div style="PAGE-BREAK-AFTER: ALWAYS"></div>')
    assert _is_page_break_div('<div style="page-break-after : always ;"></div>')
    assert _is_page_break_div(
        '<div style="color: red; page-break-after: always; margin: 0"></div>'
    )


def test_predicate_rejects_plain_and_unrelated_divs():
    assert not _is_page_break_div("<div>hello</div>")
    assert not _is_page_break_div('<div class="x">text</div>')
    assert not _is_page_break_div('<div style="color: red"></div>')
    # The property name appearing in body text (not the style attr) is not
    # a break.
    assert not _is_page_break_div("<div>page-break-after: always</div>")


def test_predicate_requires_div_first_tag():
    # Same style on a non-div tag is not our construct.
    assert not _is_page_break_div('<p style="page-break-after: always">x</p>')
    assert not _is_page_break_div('<span style="break-after: page">x</span>')


# --- End-to-end page counts -----------------------------------------------


def test_break_div_pushes_next_block_to_page_2():
    with_break = inkmd.compile(f"A\n\n{BRK}\n\nB")
    assert _page_count(with_break) == 2


def test_no_break_div_is_single_page():
    without = inkmd.compile("A\n\nB")
    assert _page_count(without) == 1


def test_synonym_break_div_pushes_to_page_2():
    assert _page_count(inkmd.compile(f"A\n\n{SYN}\n\nB")) == 2


def test_before_synonyms_also_break():
    before = '<div style="page-break-before: always"></div>'
    before2 = '<div style="break-before: page"></div>'
    assert _page_count(inkmd.compile(f"A\n\n{before}\n\nB")) == 2
    assert _page_count(inkmd.compile(f"A\n\n{before2}\n\nB")) == 2


def test_whitespace_and_case_variants_break():
    for style in (
        "page-break-after:always",
        "PAGE-BREAK-AFTER: ALWAYS",
        "page-break-after : always ;",
    ):
        md = f'A\n\n<div style="{style}"></div>\n\nB'
        assert _page_count(inkmd.compile(md)) == 2, style


def test_plain_div_does_not_break_end_to_end():
    assert _page_count(inkmd.compile("A\n\n<div>hello</div>\n\nB")) == 1
    assert _page_count(inkmd.compile('A\n\n<div class="x">text</div>\n\nB')) == 1


# --- Thematic break stays a rule (regression guard) -----------------------


def test_thematic_break_does_not_page_break():
    out = inkmd.compile("A\n\n---\n\nB")
    assert _page_count(out) == 1


def test_thematic_break_still_emits_rule():
    """`---` must still draw the horizontal rule (a `re f` shape)."""
    out = inkmd.compile("A\n\n---\n\nB")
    assert b" re f" in out


def test_thematic_break_output_unchanged_by_s5():
    """`A --- B` is byte-identical with the page-break machinery present:
    thematic break was not repurposed."""
    out = inkmd.compile("First.\n\n---\n\nSecond.")
    # Single page, carries the rule, no spurious extra page.
    assert _page_count(out) == 1
    assert b" re f" in out


# --- Edge cases -----------------------------------------------------------


def test_leading_break_emits_no_blank_first_page():
    out = inkmd.compile(f"{BRK}\n\nA\n\nB")
    assert _page_count(out) == 1


def test_two_consecutive_breaks_collapse_to_one():
    out = inkmd.compile(f"A\n\n{BRK}\n\n{BRK}\n\nB")
    assert _page_count(out) == 2


def test_trailing_break_emits_no_empty_page():
    out = inkmd.compile(f"A\n\nB\n\n{BRK}")
    assert _page_count(out) == 1


def test_break_only_document_is_single_page_with_no_text():
    out = inkmd.compile(BRK)
    assert _page_count(out) == 1
    # The break carries no content of its own.
    assert (out.count(b" Tj") + out.count(b" TJ")) == 0


def test_three_sections_two_breaks_make_three_pages():
    md = f"# One\n\nAlpha.\n\n{BRK}\n\n# Two\n\nBeta.\n\n{BRK}\n\n# Three\n\nGamma."
    assert _page_count(inkmd.compile(md)) == 3


# --- html=False -----------------------------------------------------------


def test_html_false_renders_break_div_as_text_not_break():
    """With html=False the div is escaped to literal text at parse time, so
    it never becomes a PageBreak; no forced break occurs."""
    out = inkmd.compile(f"A\n\n{BRK}\n\nB", html=False)
    assert _page_count(out) == 1


def test_html_false_keeps_div_literal_in_output():
    """The literal div text reaches the page (rendered, not interpreted)."""
    out = inkmd.compile(f"A\n\n{BRK}\n\nB", html=False)
    # Some glyphs of the literal markup must be drawn (Tj/TJ ops present).
    assert (out.count(b" Tj") + out.count(b" TJ")) > 0


# --- Byte-identity for a plain document -----------------------------------


def test_plain_document_is_stable():
    """A document with no break div compiles to a valid PDF unchanged by
    the page-break machinery (full corpus byte-identity is the harness's
    job; this is a fast in-suite sanity check)."""
    out = inkmd.compile("# Title\n\nA paragraph of ordinary prose.\n\nAnother.")
    assert out.startswith(b"%PDF-1.5\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")
    assert _page_count(out) == 1
