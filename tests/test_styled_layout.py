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


def test_wrap_runs_long_word_breaks_to_fit():
    """A single word wider than the column is broken across lines so it
    fits, rather than overflowing the column edge. No characters lost."""
    long_word = "x" * 200
    runs = [Run(f"a {long_word} b", "Helvetica", 12)]
    lines = wrap_runs(runs, column_width=50)
    # Every line fits within the column (allowing a tiny rounding slack).
    for line in lines:
        w = sum(text_width(r.text, r.font, r.size) for r in line)
        assert w <= 50 + 0.5, f"line exceeds column width: {w}"
    # All 200 x's survive, in order, across however many lines it took.
    joined = "".join(r.text for line in lines for r in line)
    assert "x" * 200 in joined.replace(" ", "")


def test_wrap_runs_breaks_long_identifier_at_underscores():
    """A long snake_case identifier (e.g. a code span) wider than the
    column breaks at underscores so it fits, rather than overflowing."""
    ident = "process_emphasis_with_a_really_long_function_name_here"
    runs = [Run(ident, "Courier", 12)]
    lines = wrap_runs(runs, column_width=120)
    assert len(lines) >= 2, "long identifier should wrap to multiple lines"
    for line in lines:
        w = sum(text_width(r.text, r.font, r.size) for r in line)
        assert w <= 120 + 0.5, f"wrapped line exceeds column width: {w}"
    # No characters lost; order preserved.
    joined = "".join(r.text for line in lines for r in line)
    assert joined == ident
    # At least one break landed after an underscore (preferred break point).
    assert any(line and "".join(r.text for r in line).endswith("_") for line in lines)


def test_wrap_runs_breaks_long_dotted_path_at_dots():
    """A long dotted path breaks at '.' boundaries."""
    path = "RenderedBlock.positioned_runs.overflow.the.cell.boundary.here"
    runs = [Run(path, "Courier", 12)]
    lines = wrap_runs(runs, column_width=140)
    for line in lines:
        w = sum(text_width(r.text, r.font, r.size) for r in line)
        assert w <= 140 + 0.5, f"wrapped line exceeds column width: {w}"
    joined = "".join(r.text for line in lines for r in line)
    assert joined == path


def test_table_with_long_codespan_stays_within_table_width():
    """End-to-end: a table cell with a long inline code span must not
    place any run past the table's right edge (the launch-blocking
    overflow bug). Regression test for the 2026-05-30 fix."""
    import inkmd
    from inkmd.parser import parse
    from inkmd.render import _render_table, TABLE_AVAILABLE_WIDTH, FAMILIES
    from inkmd.ast import Table

    md = (
        "| Step | Action | Detail |\n"
        "|------|--------|--------|\n"
        "| 1 | Re-run `layout` | Calls "
        "`process_emphasis_with_a_really_long_function_name_here` and bleeds |\n"
    )
    doc = parse(md)
    table = next(b for b in doc.blocks if isinstance(b, Table))
    rendered = _render_table(table, FAMILIES["helvetica"])

    # Every positioned run must sit within the table's right edge.
    from inkmd.fonts import text_width as _tw
    max_x = 0.0
    for _baseline, line in rendered.prepositioned_lines:
        for run in line:
            right = run.x_rel + _tw(run.text, run.font, run.size)
            max_x = max(max_x, right)
    assert max_x <= TABLE_AVAILABLE_WIDTH + 0.5, (
        f"content right edge {max_x} exceeds table width {TABLE_AVAILABLE_WIDTH}"
    )

    # And the document compiles to a valid PDF.
    assert inkmd.compile(md)[:4] == b"%PDF"


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


def test_ordered_list_marker_does_not_overlap_body_at_two_digits():
    """Regression: an ordered list reaching item 10+ must not let the
    multi-digit marker ('10. ') overrun the body text. The body indent
    widens to the widest marker in the list."""
    import inkmd
    from inkmd.parser import parse
    from inkmd.render import render_document, FAMILIES

    md = "\n".join(f"{i}. item number {i}" for i in range(1, 13))
    blocks = render_document(parse(md), FAMILIES["helvetica"])
    pages = paginate_runs(blocks, page_width=612, page_height=792)
    for page in pages:
        for line in page.lines:
            runs = line.runs
            if len(runs) < 2:
                continue
            marker = runs[0]
            marker_end = marker.x + text_width(marker.text, marker.font, marker.size)
            body_start = runs[1].x
            assert marker_end <= body_start + 1e-6, (
                f"marker {marker.text!r} ends at {marker_end} but body starts "
                f"at {body_start} (overlap)"
            )
    # Sanity: a short 1..4 list keeps the tight default indent (no
    # over-widening) — body should still be at the standard 18pt step.
    short = render_document(parse("1. x\n2. x\n3. x\n4. x"), FAMILIES["helvetica"])
    assert short[0].body_indent == 18.0
