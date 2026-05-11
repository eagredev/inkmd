"""Layout tests — milestone 0.0.2: wrapping and pagination."""

from __future__ import annotations

from inkmd.fonts import text_width
from inkmd.layout import (
    DEFAULT_FONT,
    DEFAULT_FONT_SIZE,
    DEFAULT_LINE_HEIGHT,
    DEFAULT_MARGIN,
    paginate,
    split_paragraphs,
    wrap_paragraph,
)


# --- wrap_paragraph --------------------------------------------------------


def test_wrap_short_paragraph_one_line():
    lines = wrap_paragraph("hello world", column_width=500)
    assert lines == ["hello world"]


def test_wrap_empty_paragraph_yields_nothing():
    assert wrap_paragraph("", column_width=500) == []
    assert wrap_paragraph("   ", column_width=500) == []


def test_wrap_breaks_when_line_overflows():
    """A column too narrow for the whole sentence must break it."""
    # 50pt is much narrower than "hello world" at 12pt Helvetica
    lines = wrap_paragraph("hello world today", column_width=50)
    assert len(lines) >= 2
    # No line should be wider than the column (modulo long single words).
    for line in lines:
        # Long words can overflow; but multi-word lines should fit.
        if " " in line:
            assert text_width(line, DEFAULT_FONT, DEFAULT_FONT_SIZE) <= 50


def test_wrap_preserves_word_order():
    text = "one two three four five six seven eight nine ten"
    lines = wrap_paragraph(text, column_width=80)
    rejoined = " ".join(lines)
    assert rejoined == text


def test_wrap_long_word_overflows_alone():
    """A single word wider than the column gets its own line."""
    long_word = "x" * 200
    lines = wrap_paragraph(f"a {long_word} b", column_width=50)
    assert long_word in lines


def test_wrap_collapses_internal_whitespace():
    """Multiple spaces between words collapse to one."""
    lines = wrap_paragraph("hello    world", column_width=500)
    assert lines == ["hello world"]


# --- split_paragraphs ------------------------------------------------------


def test_split_paragraphs_on_blank_lines():
    text = "First paragraph.\n\nSecond paragraph."
    assert split_paragraphs(text) == ["First paragraph.", "Second paragraph."]


def test_split_paragraphs_drops_empty():
    text = "\n\n\nOne\n\n\n\nTwo\n\n"
    assert split_paragraphs(text) == ["One", "Two"]


def test_split_paragraphs_flattens_internal_newlines():
    """A single newline inside a paragraph becomes a space."""
    text = "Line one\nLine two\nLine three"
    assert split_paragraphs(text) == ["Line one Line two Line three"]


# --- paginate --------------------------------------------------------------


def test_paginate_short_text_one_page():
    pages = paginate(["Short paragraph."], page_width=612, page_height=792)
    assert len(pages) == 1
    assert len(pages[0].lines) == 1
    assert pages[0].lines[0].text == "Short paragraph."


def test_paginate_empty_input_no_pages():
    """No paragraphs in → no pages out (text_pdf handles the empty case)."""
    assert paginate([], page_width=612, page_height=792) == []


def test_paginate_line_positions_descending_y():
    """On a single page, line y-coordinates should decrease (PDF coords)."""
    paragraphs = ["one", "two", "three", "four"]
    pages = paginate(paragraphs, page_width=612, page_height=792)
    assert len(pages) == 1
    ys = [line.y for line in pages[0].lines]
    assert ys == sorted(ys, reverse=True), f"y not strictly descending: {ys}"


def test_paginate_first_line_within_top_margin():
    """The first line's baseline must sit at most ``line_height`` below the top margin."""
    pages = paginate(["only paragraph"], page_width=612, page_height=792)
    first_line = pages[0].lines[0]
    expected_y = 792 - DEFAULT_MARGIN - DEFAULT_LINE_HEIGHT
    assert abs(first_line.y - expected_y) < 1e-6


def test_paginate_breaks_to_new_page_when_full():
    """A document tall enough to overflow must produce multiple pages."""
    # Letter page minus 2x72 margins = 648 usable points vertically.
    # At 14.4pt line height that's 45 lines per page. 100 paragraphs of
    # one line each must spill across multiple pages.
    paragraphs = [f"paragraph {i}" for i in range(100)]
    pages = paginate(paragraphs, page_width=612, page_height=792)
    assert len(pages) >= 2


def test_paginate_no_lines_below_bottom_margin():
    """Every line on every page must sit at or above the bottom margin."""
    paragraphs = [f"para {i}" for i in range(60)]
    pages = paginate(paragraphs, page_width=612, page_height=792)
    for page in pages:
        for line in page.lines:
            assert line.y >= DEFAULT_MARGIN - 1e-6, (
                f"line at y={line.y} is below bottom margin {DEFAULT_MARGIN}"
            )


def test_paginate_line_x_equals_left_margin():
    pages = paginate(["hello"], page_width=612, page_height=792)
    assert pages[0].lines[0].x == DEFAULT_MARGIN
