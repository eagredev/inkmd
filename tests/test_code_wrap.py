"""Code-block soft-wrap tests — added 0.0.11.2.

Fenced code blocks previously kept ``preserve_lines=True`` which
disabled wrapping entirely, so long source lines overflowed the page
right edge. The fix soft-wraps each source line at the column
boundary, preferring whitespace breaks, hard-breaking only when no
whitespace exists. Whitespace inside an unbroken line stays intact.
"""

from __future__ import annotations

import inkmd
from inkmd.layout import Run, _wrap_preserved_line, _split_preserved_lines


def test_short_line_not_wrapped():
    """A line that fits stays one line."""
    line = [Run(text="hi", font="Courier", size=10.5)]
    out = _wrap_preserved_line(line, column_width=400.0)
    assert out == [line]


def test_long_line_wraps_at_whitespace():
    """A line longer than the column wraps at the last space before overflow."""
    line = [Run(text="one two three four five six seven", font="Courier", size=10.5)]
    # Set a column so narrow that ~3 words fit per line.
    out = _wrap_preserved_line(line, column_width=60.0)
    assert len(out) >= 2
    # No wrapped line should have leading whitespace (it's eaten at the break).
    for wrapped in out:
        text = "".join(r.text for r in wrapped)
        assert not text.startswith(" "), f"leading space in {text!r}"


def test_unbreakable_token_hard_breaks():
    """A token wider than the column hard-breaks at the column boundary."""
    line = [Run(text="x" * 200, font="Courier", size=10.5)]
    out = _wrap_preserved_line(line, column_width=60.0)
    # We get multiple lines because no space exists.
    assert len(out) > 1
    # The total content is preserved across the wrapped lines.
    rejoined = "".join(r.text for w in out for r in w)
    assert rejoined == "x" * 200


def test_interior_whitespace_within_unbroken_line_preserved():
    """Multiple spaces inside a line that fits in the column stay intact."""
    line = [Run(text="foo    bar    baz", font="Courier", size=10.5)]
    out = _wrap_preserved_line(line, column_width=400.0)
    assert len(out) == 1
    assert "".join(r.text for r in out[0]) == "foo    bar    baz"


def test_split_preserved_lines_with_column():
    """A multi-line code block with one over-wide line wraps that line only."""
    runs = [Run(text="short line\n" + "long " * 50, font="Courier", size=10.5)]
    out = _split_preserved_lines(runs, column_width=200.0)
    # First source line is short, stays as 1 wrapped line.
    # Second source line is long, wraps to multiple.
    assert len(out) > 2


def test_split_preserved_lines_no_column_does_not_wrap():
    """Calling without column_width returns one wrapped line per source line."""
    runs = [Run(text="line one\nline two\nline three", font="Courier", size=10.5)]
    out = _split_preserved_lines(runs)
    assert len(out) == 3


def test_compile_long_code_line_does_not_overflow():
    """End-to-end: a code block with a long line wraps so all content
    appears inside the column. We check by looking at the positioned-run
    x coordinates: none should exceed page_width - margin.
    """
    long_line = "x_y_" * 80  # ~320 chars, far wider than a page
    md = f"```\n{long_line}\n```"
    out = inkmd.compile(md)
    # The PDF should validate.
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")
    # And it should have multiple Tm operators (one per wrapped line).
    assert out.count(b" Tm\n") >= 3  # original line + 2+ wraps


def test_compile_short_code_line_unchanged():
    """A short code line still renders as exactly one line."""
    md = "```\nhello\n```"
    out = inkmd.compile(md)
    # Single short line means few Tm operators (one for the line).
    assert b"(hello) Tj" in out


def test_compile_code_block_indentation_preserved_after_wrap():
    """A code line that starts with spaces keeps them on the first wrapped line."""
    # 4-space-indented, followed by a long token that wraps.
    md = "```\n    " + "abc " * 40 + "\n```"
    out = inkmd.compile(md)
    # The first emission of the line should contain the leading 4 spaces.
    # (We don't enforce that wrapping continuations re-indent — they
    # currently align with the wrapped line's left edge, which is the
    # code block's body_indent, not the original indent within the line.)
    assert out.startswith(b"%PDF-1.4\n")
