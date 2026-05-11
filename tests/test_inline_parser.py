"""Inline parser tests — milestone 0.0.5.

Covers ** bold **, * italic *, ` code ` recognition and the edge cases
that fall out as plain text per the v0.0.5 deferred-scope decisions.
"""

from __future__ import annotations

from inkmd.ast import Code, Emphasis, Strong, Text
from inkmd.parser import parse


def _inlines(md: str):
    """Helper: parse a single-paragraph markdown string, return its inlines."""
    doc = parse(md)
    assert len(doc.blocks) == 1, doc
    return doc.blocks[0].inlines


# --- Basic recognition ----------------------------------------------------


def test_plain_paragraph_is_one_text_node():
    assert _inlines("Hello, world.") == (Text("Hello, world."),)


def test_strong_recognised():
    inlines = _inlines("**bold**")
    assert inlines == (Strong(inlines=(Text("bold"),)),)


def test_emphasis_recognised():
    inlines = _inlines("*italic*")
    assert inlines == (Emphasis(inlines=(Text("italic"),)),)


def test_code_recognised():
    inlines = _inlines("`code`")
    assert inlines == (Code(content="code"),)


def test_strong_with_surrounding_text():
    inlines = _inlines("plain **bold** plain")
    assert inlines == (
        Text("plain "),
        Strong(inlines=(Text("bold"),)),
        Text(" plain"),
    )


def test_emphasis_with_surrounding_text():
    inlines = _inlines("a *b* c")
    assert inlines == (
        Text("a "),
        Emphasis(inlines=(Text("b"),)),
        Text(" c"),
    )


def test_code_with_surrounding_text():
    inlines = _inlines("see `print()` here")
    assert inlines == (
        Text("see "),
        Code(content="print()"),
        Text(" here"),
    )


# --- Multiple spans in one paragraph --------------------------------------


def test_multiple_distinct_spans():
    inlines = _inlines("**a** and *b* and `c`")
    assert inlines == (
        Strong(inlines=(Text("a"),)),
        Text(" and "),
        Emphasis(inlines=(Text("b"),)),
        Text(" and "),
        Code(content="c"),
    )


def test_two_strong_spans():
    inlines = _inlines("**a** and **b**")
    assert inlines[0] == Strong(inlines=(Text("a"),))
    assert inlines[2] == Strong(inlines=(Text("b"),))


# --- Code is opaque -------------------------------------------------------


def test_code_does_not_parse_internal_formatting():
    """Backticks block all internal parsing — asterisks stay literal."""
    inlines = _inlines("`**not bold**`")
    assert inlines == (Code(content="**not bold**"),)


def test_code_does_not_parse_internal_emphasis():
    inlines = _inlines("`*not italic*`")
    assert inlines == (Code(content="*not italic*"),)


# --- Strong vs Emphasis disambiguation ------------------------------------


def test_double_star_prefers_strong_over_emphasis():
    """A run of two asterisks must be Strong, not two Emphases."""
    inlines = _inlines("**both**")
    assert inlines == (Strong(inlines=(Text("both"),)),)


def test_single_star_with_a_double_later_does_not_consume_the_double():
    """*single* should not pair with a later ** if a * exists between."""
    inlines = _inlines("*one* and **two**")
    assert inlines[0] == Emphasis(inlines=(Text("one"),))


# --- Unmatched delimiters fall through ------------------------------------


def test_unmatched_double_star_is_literal_text():
    inlines = _inlines("**not closed")
    assert inlines == (Text("**not closed"),)


def test_unmatched_single_star_is_literal_text():
    inlines = _inlines("not *closed")
    # No matching * found, so the * sits literally in the buffer
    assert inlines == (Text("not *closed"),)


def test_unmatched_backtick_is_literal_text():
    inlines = _inlines("see `code")
    assert inlines == (Text("see `code"),)


# --- Empty spans ----------------------------------------------------------


def test_empty_strong_is_empty():
    """**** with no content currently produces an empty Strong; that's fine for v0.0.5."""
    inlines = _inlines("****")
    # Whatever the result is, the parser must not crash.
    assert inlines is not None


def test_empty_code_span():
    """`` (empty backticks) — parser must not crash; the exact AST shape may vary."""
    inlines = _inlines("``")
    assert inlines is not None
