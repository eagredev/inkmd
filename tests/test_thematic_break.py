"""Thematic-break tests — milestone 0.0.11.4.

Covers CommonMark §4.1: lines of 3+ `-`, `*`, or `_` (same char,
optional internal spaces/tabs, 0-3 indent) render as a horizontal rule.
"""

from __future__ import annotations

import inkmd
from inkmd.ast import Heading, Paragraph, ThematicBreak, Text
from inkmd.parser import parse


def _blocks(md: str):
    return parse(md).blocks


# --- Basic forms ----------------------------------------------------------


def test_three_dashes():
    assert _blocks("---") == (ThematicBreak(),)


def test_three_asterisks():
    assert _blocks("***") == (ThematicBreak(),)


def test_three_underscores():
    assert _blocks("___") == (ThematicBreak(),)


def test_more_than_three():
    assert _blocks("----------") == (ThematicBreak(),)


def test_with_internal_spaces():
    assert _blocks("- - -") == (ThematicBreak(),)
    assert _blocks("* * *") == (ThematicBreak(),)
    assert _blocks(" ---  ") == (ThematicBreak(),)


def test_up_to_three_space_indent_allowed():
    for indent in range(4):
        body = (" " * indent) + "---"
        if indent < 4:
            assert _blocks(body) == (ThematicBreak(),), f"indent={indent}"


def test_four_space_indent_is_not_thematic_break():
    """4 spaces of indent is a code-block context (v0.1 doesn't support
    indented code blocks yet, so it becomes paragraph)."""
    blocks = _blocks("    ---")
    assert not any(isinstance(b, ThematicBreak) for b in blocks)


# --- Negative cases -------------------------------------------------------


def test_two_dashes_is_not_thematic_break():
    blocks = _blocks("--")
    assert not any(isinstance(b, ThematicBreak) for b in blocks)


def test_mixed_chars_not_thematic_break():
    """`-*-` mixes characters → not a thematic break."""
    blocks = _blocks("-*-")
    assert not any(isinstance(b, ThematicBreak) for b in blocks)


def test_dashes_with_text_not_thematic_break():
    blocks = _blocks("--- text")
    assert not any(isinstance(b, ThematicBreak) for b in blocks)


# --- Setext priority ------------------------------------------------------


def test_setext_h2_wins_over_thematic_break():
    """`text\\n---` is Setext H2, NOT paragraph + thematic break.

    CommonMark §4.1 example 30: the dashes attach to the previous
    paragraph as a Setext H2 underline.
    """
    blocks = _blocks("Title\n---")
    assert len(blocks) == 1
    assert isinstance(blocks[0], Heading)
    assert blocks[0].level == 2


def test_thematic_break_after_blank_line():
    """`Para\\n\\n---` is paragraph then thematic break (blank breaks
    the setext attachment)."""
    blocks = _blocks("Para\n\n---")
    assert len(blocks) == 2
    assert isinstance(blocks[0], Paragraph)
    assert isinstance(blocks[1], ThematicBreak)


def test_thematic_break_using_underscores_after_paragraph():
    """`___` is unambiguous — no Setext underline form uses `_`."""
    blocks = _blocks("Para\n___")
    # `___` after a paragraph: still a thematic break (Setext only uses `=` or `-`).
    assert len(blocks) == 2
    assert isinstance(blocks[0], Paragraph)
    assert isinstance(blocks[1], ThematicBreak)


# --- Multi-block context --------------------------------------------------


def test_thematic_break_between_paragraphs():
    blocks = _blocks("First.\n\n---\n\nSecond.")
    assert len(blocks) == 3
    assert isinstance(blocks[0], Paragraph)
    assert isinstance(blocks[1], ThematicBreak)
    assert isinstance(blocks[2], Paragraph)


def test_consecutive_thematic_breaks():
    blocks = _blocks("---\n\n---\n\n---")
    assert blocks == (ThematicBreak(), ThematicBreak(), ThematicBreak())


# --- End-to-end -----------------------------------------------------------


def test_compile_thematic_break_produces_valid_pdf():
    out = inkmd.compile("Before.\n\n---\n\nAfter.")
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_compile_thematic_break_emits_rectangle():
    """The horizontal rule is a `re f` shape pair in the content stream."""
    out = inkmd.compile("Before.\n\n---\n\nAfter.")
    assert b" re f" in out
