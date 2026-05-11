"""Tests for the styled-runs layout path — milestone 0.0.3."""

from __future__ import annotations

from inkmd.fonts import text_width
from inkmd.layout import (
    DEFAULT_MARGIN,
    Page,
    PositionedRun,
    Run,
    StyledLine,
    _tokenise_runs,
    paginate_runs,
    wrap_runs,
)


# --- _tokenise_runs --------------------------------------------------------


def test_tokenise_splits_on_whitespace_within_a_run():
    runs = [Run("hello world", "Helvetica", 12)]
    tokens = _tokenise_runs(runs)
    texts = [t.text for t in tokens]
    assert texts == ["hello", " ", "world"]


def test_tokenise_preserves_style_per_token():
    runs = [
        Run("hello", "Helvetica-Bold", 12),
        Run(" world", "Helvetica", 12),
    ]
    tokens = _tokenise_runs(runs)
    assert tokens[0].font == "Helvetica-Bold"
    assert tokens[0].text == "hello"
    # The leading space of the second run inherits the regular font.
    assert tokens[1].font == "Helvetica"
    assert tokens[1].text == " "
    assert tokens[2].text == "world"


def test_tokenise_collapses_internal_whitespace_runs():
    """Multiple whitespace chars in a row collapse to a single space token."""
    runs = [Run("a   b", "Helvetica", 12)]
    tokens = _tokenise_runs(runs)
    assert [t.text for t in tokens] == ["a", " ", "b"]


# --- wrap_runs -------------------------------------------------------------


def test_wrap_runs_fits_short_paragraph_on_one_line():
    runs = [
        Run("hello ", "Helvetica", 12),
        Run("world", "Helvetica-Bold", 12),
    ]
    lines = wrap_runs(runs, column_width=500)
    assert len(lines) == 1
    rejoined = "".join(r.text for r in lines[0])
    assert rejoined == "hello world"


def test_wrap_runs_preserves_run_styles_after_wrapping():
    runs = [
        Run("alpha beta gamma ", "Helvetica", 12),
        Run("delta epsilon zeta", "Helvetica-Bold", 12),
    ]
    lines = wrap_runs(runs, column_width=80)
    # There must be at least one line containing both fonts somewhere.
    fonts_seen = {r.font for line in lines for r in line}
    assert "Helvetica" in fonts_seen
    assert "Helvetica-Bold" in fonts_seen


def test_wrap_runs_strips_leading_and_trailing_whitespace():
    runs = [Run("alpha beta gamma", "Helvetica", 12)]
    lines = wrap_runs(runs, column_width=60)
    for line in lines:
        assert not line[0].text.isspace(), f"line starts with whitespace: {line}"
        assert not line[-1].text.isspace(), f"line ends with whitespace: {line}"


def test_wrap_runs_empty_input():
    assert wrap_runs([], column_width=500) == []
    assert wrap_runs([Run("", "Helvetica", 12)], column_width=500) == []


def test_wrap_runs_long_word_overflows_alone():
    """A single word wider than the column must still produce a line."""
    long_word = "x" * 200
    runs = [Run(f"a {long_word} b", "Helvetica", 12)]
    lines = wrap_runs(runs, column_width=50)
    found = any(long_word in "".join(r.text for r in line) for line in lines)
    assert found


def test_wrap_runs_bold_takes_more_space_than_regular():
    """Bold Helvetica is wider per-char; the same text should wrap more aggressively in bold."""
    text = "alpha beta gamma delta epsilon"
    plain = wrap_runs([Run(text, "Helvetica", 12)], column_width=120)
    bold = wrap_runs([Run(text, "Helvetica-Bold", 12)], column_width=120)
    # Bold version should need at least as many lines as plain.
    assert len(bold) >= len(plain)


# --- paginate_runs ---------------------------------------------------------


def test_paginate_runs_short_input_one_page():
    paragraphs = [[Run("hello world", "Helvetica", 12)]]
    pages = paginate_runs(paragraphs, page_width=612, page_height=792)
    assert len(pages) == 1
    assert len(pages[0].lines) == 1
    line = pages[0].lines[0]
    assert isinstance(line, StyledLine)
    assert isinstance(line.runs[0], PositionedRun)


def test_paginate_runs_positions_runs_on_one_baseline():
    """All runs on a single line must share the same y coordinate."""
    paragraphs = [[
        Run("regular ", "Helvetica", 12),
        Run("bold ", "Helvetica-Bold", 12),
        Run("italic ", "Helvetica-Oblique", 12),
        Run("code", "Courier", 12),
    ]]
    pages = paginate_runs(paragraphs, page_width=612, page_height=792)
    line = pages[0].lines[0]
    ys = {r.y for r in line.runs}
    assert len(ys) == 1, f"runs on same line should share y, got {ys}"


def test_paginate_runs_x_increases_left_to_right():
    paragraphs = [[
        Run("alpha ", "Helvetica", 12),
        Run("beta ", "Helvetica-Bold", 12),
        Run("gamma", "Helvetica-Oblique", 12),
    ]]
    pages = paginate_runs(paragraphs, page_width=612, page_height=792)
    line = pages[0].lines[0]
    xs = [r.x for r in line.runs]
    assert xs == sorted(xs), f"x not monotonically increasing: {xs}"


def test_paginate_runs_breaks_across_pages():
    """Many short paragraphs should produce multiple pages."""
    paragraphs = [
        [Run(f"paragraph {i}", "Helvetica", 12)] for i in range(120)
    ]
    pages = paginate_runs(paragraphs, page_width=612, page_height=792)
    assert len(pages) >= 2


def test_paginate_runs_respects_bottom_margin():
    paragraphs = [
        [Run(f"para {i}", "Helvetica", 12)] for i in range(80)
    ]
    pages = paginate_runs(paragraphs, page_width=612, page_height=792)
    for page in pages:
        for line in page.lines:
            for run in line.runs:
                assert run.y >= DEFAULT_MARGIN - 1e-6


def test_paginate_runs_first_run_at_left_margin():
    paragraphs = [[Run("hello", "Helvetica", 12)]]
    pages = paginate_runs(paragraphs, page_width=612, page_height=792)
    assert pages[0].lines[0].runs[0].x == DEFAULT_MARGIN


def test_paginate_runs_subsequent_run_x_matches_first_run_width():
    """The second run's x must equal the first run's x + its rendered width."""
    runs = [
        Run("alpha", "Helvetica", 12),
        Run(" beta", "Helvetica-Bold", 12),
    ]
    pages = paginate_runs([runs], page_width=612, page_height=792)
    positioned = pages[0].lines[0].runs
    # The tokeniser splits the second run on its leading space, so
    # positioned will contain: alpha, " ", beta — or some splitting
    # like that. We assert that x values are monotonic and that
    # consecutive xs differ by the previous text's width.
    for i in range(1, len(positioned)):
        prev = positioned[i - 1]
        expected = prev.x + text_width(prev.text, prev.font, prev.size)
        assert abs(positioned[i].x - expected) < 1e-6
