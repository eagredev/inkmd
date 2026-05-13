"""CommonMark hard-line-break tests (section 6.7).

Two forms produce a hard break (HardBreak inline node):
    foo  <newline>baz    — two or more trailing spaces
    foo\\<newline>baz    — backslash immediately before newline

Single trailing space + newline is a soft break (a literal newline in
the AST text). Hard breaks at the end of a paragraph degrade to plain
line endings (no <br /> in HTML output, no forced wrap in PDF).
"""

from __future__ import annotations

import re

import inkmd
from inkmd.ast import HardBreak, Text
from inkmd.parser import parse


def _inlines(md: str):
    return parse(md).blocks[0].inlines


def test_two_trailing_spaces_become_hardbreak():
    inlines = _inlines("foo  \nbaz")
    assert HardBreak() in inlines


def test_many_trailing_spaces_also_work():
    inlines = _inlines("foo        \nbaz")
    assert HardBreak() in inlines


def test_single_trailing_space_is_soft_break():
    inlines = _inlines("foo \nbaz")
    assert HardBreak() not in inlines
    # AST may preserve the trailing space verbatim; HTML serialisation
    # is what the spec defines (trailing space disappears there). We
    # accept either AST form as long as no HardBreak was emitted.
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert text in ("foo\nbaz", "foo \nbaz")


def test_no_trailing_space_is_soft_break():
    inlines = _inlines("foo\nbaz")
    assert HardBreak() not in inlines


def test_backslash_newline_is_hardbreak():
    inlines = _inlines("foo\\\nbaz")
    assert HardBreak() in inlines


def test_backslash_followed_by_escapable_is_escape_not_break():
    inlines = _inlines("foo\\*bar")
    assert HardBreak() not in inlines


def test_leading_whitespace_after_hardbreak_is_stripped():
    inlines = _inlines("foo  \n     bar")
    text_parts = [n.content for n in inlines if isinstance(n, Text)]
    assert text_parts == ["foo", "bar"]


def test_backslash_leading_whitespace_after():
    inlines = _inlines("foo\\\n     bar")
    text_parts = [n.content for n in inlines if isinstance(n, Text)]
    assert text_parts == ["foo", "bar"]


def test_hardbreak_inside_emphasis():
    from inkmd.ast import Emphasis
    inlines = _inlines("*foo  \nbar*")
    em = next(n for n in inlines if isinstance(n, Emphasis))
    assert HardBreak() in em.inlines


def test_hardbreak_at_end_of_paragraph_degrades():
    inlines = _inlines("foo  ")
    assert HardBreak() not in inlines
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert text == "foo"


def test_pdf_hardbreak_starts_new_line():
    pdf = inkmd.compile("Line one  \nLine two")
    ys = sorted({float(y) for _x, y in re.findall(rb"1 0 0 1 (\S+) (\S+) Tm", pdf)})
    assert len(ys) >= 2, f"Expected at least two y values, got {ys}"


def test_pdf_softbreak_keeps_one_line():
    pdf = inkmd.compile("Line one\nLine two")
    ys = sorted({float(y) for _x, y in re.findall(rb"1 0 0 1 (\S+) (\S+) Tm", pdf)})
    assert len(ys) == 1
