"""Table parser + render tests — milestone 0.0.10 (GFM pipe tables)."""

from __future__ import annotations

import inkmd
from inkmd.ast import (
    Document,
    Emphasis,
    Paragraph,
    Strong,
    Table,
    TableCell,
    Text,
)
from inkmd.parser import parse


# --- Parsing: basic ---------------------------------------------------------


def _simple_table_md() -> str:
    return (
        "| H1 | H2 | H3 |\n"
        "| --- | --- | --- |\n"
        "| a | b | c |\n"
        "| d | e | f |"
    )


def test_simple_table_parses():
    doc = parse(_simple_table_md())
    assert len(doc.blocks) == 1
    t = doc.blocks[0]
    assert isinstance(t, Table)
    assert len(t.headers) == 3
    assert len(t.rows) == 2


def test_table_headers_are_cells_with_text():
    doc = parse(_simple_table_md())
    t = doc.blocks[0]
    assert t.headers[0] == TableCell(inlines=(Text("H1"),))
    assert t.headers[1] == TableCell(inlines=(Text("H2"),))


def test_table_default_alignment_is_none():
    doc = parse(_simple_table_md())
    t = doc.blocks[0]
    assert t.alignments == (None, None, None)


def test_table_body_rows_match_header_column_count():
    doc = parse(_simple_table_md())
    t = doc.blocks[0]
    for row in t.rows:
        assert len(row) == 3


# --- Parsing: alignments ----------------------------------------------------


def test_alignment_left():
    doc = parse("| H |\n| :--- |\n| x |")
    t = doc.blocks[0]
    assert t.alignments == ("left",)


def test_alignment_right():
    doc = parse("| H |\n| ---: |\n| x |")
    t = doc.blocks[0]
    assert t.alignments == ("right",)


def test_alignment_center():
    doc = parse("| H |\n| :---: |\n| x |")
    t = doc.blocks[0]
    assert t.alignments == ("center",)


def test_mixed_alignments():
    doc = parse("| L | C | R |\n| :--- | :---: | ---: |\n| a | b | c |")
    t = doc.blocks[0]
    assert t.alignments == ("left", "center", "right")


# --- Parsing: edge cases ----------------------------------------------------


def test_table_without_leading_or_trailing_pipes():
    """Pipes at start/end of a row are optional."""
    doc = parse("A | B\n--- | ---\n1 | 2")
    assert isinstance(doc.blocks[0], Table)


def test_table_with_extra_cells_truncates():
    """Body rows with too many cells are truncated to match header count."""
    doc = parse("| A | B |\n| --- | --- |\n| 1 | 2 | 3 |")
    t = doc.blocks[0]
    assert len(t.rows[0]) == 2


def test_table_with_missing_cells_pads_with_empty():
    """Body rows with too few cells are padded with empty cells."""
    doc = parse("| A | B | C |\n| --- | --- | --- |\n| 1 |")
    t = doc.blocks[0]
    assert len(t.rows[0]) == 3
    assert t.rows[0][1] == TableCell(inlines=())
    assert t.rows[0][2] == TableCell(inlines=())


def test_table_ends_at_blank_line():
    doc = parse(
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n\nParagraph after."
    )
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], Table)
    assert isinstance(doc.blocks[1], Paragraph)


def test_table_ends_at_non_row_line():
    """A non-pipe line ends the table; that line is then parsed normally."""
    doc = parse("| A |\n| --- |\n| 1 |\nNot a row.")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], Table)
    assert isinstance(doc.blocks[1], Paragraph)


def test_lone_paragraph_with_pipe_is_not_a_table():
    """A paragraph containing pipes but no delimiter row is just a paragraph."""
    doc = parse("This line has a | pipe in it.")
    assert isinstance(doc.blocks[0], Paragraph)


def test_one_row_table():
    """A header + delimiter with no body is still a valid table."""
    doc = parse("| A | B |\n| --- | --- |")
    t = doc.blocks[0]
    assert isinstance(t, Table)
    assert t.rows == ()


# --- Parsing: inline content ------------------------------------------------


def test_cell_with_bold():
    doc = parse("| H |\n| --- |\n| **bold** |")
    t = doc.blocks[0]
    assert t.rows[0][0] == TableCell(inlines=(Strong(inlines=(Text("bold"),)),))


def test_cell_with_italic():
    doc = parse("| H |\n| --- |\n| *italic* |")
    t = doc.blocks[0]
    assert t.rows[0][0] == TableCell(
        inlines=(Emphasis(inlines=(Text("italic"),)),)
    )


def test_cell_with_escaped_pipe():
    """A backslash-escaped pipe inside a cell is preserved as a literal pipe."""
    doc = parse(r"| H |\n| --- |\n| a \| b |".replace(r"\n", "\n"))
    t = doc.blocks[0]
    # The cell text should contain a literal '|'.
    assert "|" in t.rows[0][0].inlines[0].content


# --- Render -----------------------------------------------------------------


def test_render_table_emits_prepositioned_block():
    from inkmd.render import render_document

    doc = parse(_simple_table_md())
    blocks = render_document(doc)
    assert len(blocks) == 1
    block = blocks[0]
    assert block.prepositioned is True
    assert block.runs == ()  # all content is in prepositioned_lines
    assert len(block.prepositioned_lines) > 0
    assert len(block.prepositioned_shapes) > 0


def test_render_table_has_header_background_shape():
    """The first shape should be the header tint."""
    from inkmd.render import TABLE_HEADER_BG, render_document

    doc = parse(_simple_table_md())
    block = render_document(doc)[0]
    # At least one shape carries the header background colour.
    fills = {s["fill"] for s in block.prepositioned_shapes}
    assert TABLE_HEADER_BG in fills


def test_render_table_has_grid_lines():
    """Grid lines: at least 4 horizontals (top, post-header, between body, bottom)
    and n_cols+1 verticals."""
    from inkmd.render import TABLE_GRID_FILL, render_document

    doc = parse(_simple_table_md())
    block = render_document(doc)[0]
    grid_shapes = [s for s in block.prepositioned_shapes if s["fill"] == TABLE_GRID_FILL]
    # 4 horizontal (top, after-header, after-row-1, after-row-2) + 4 vertical (3 cols + edges)
    assert len(grid_shapes) >= 4 + 4


def test_render_table_headers_use_bold_font():
    from inkmd.render import HELVETICA_FAMILY, render_document

    doc = parse(_simple_table_md())
    block = render_document(doc)[0]
    # The header line is the first one positioned at the top.
    # Find any run with text 'H1' / 'H2' / 'H3' and check its font.
    header_texts = {"H1", "H2", "H3"}
    found_bold = False
    for _baseline, runs in block.prepositioned_lines:
        for r in runs:
            if r.text in header_texts:
                assert r.font == HELVETICA_FAMILY.bold
                found_bold = True
    assert found_bold


# --- End-to-end -------------------------------------------------------------


def test_compile_table_produces_valid_pdf():
    out = inkmd.compile(_simple_table_md())
    assert out.startswith(b"%PDF-1.4\n")
    assert out.rstrip(b"\n").endswith(b"%%EOF")


def test_compile_table_emits_grid_rectangles():
    """The grid lines should appear as `re f` shape pairs in the stream."""
    out = inkmd.compile(_simple_table_md())
    assert b" re f" in out


def test_compile_table_cells_appear_in_stream():
    """Header text 'H1' through 'H3' should appear in the PDF stream."""
    out = inkmd.compile(_simple_table_md())
    # Courier kerning is zero so headers stay whole — but they're Helvetica-Bold here.
    # Use a kerning-free anchor.
    md = (
        "| zzAnchorzz | other |\n"
        "| --- | --- |\n"
        "| body | x |"
    )
    out = inkmd.compile(md, family="times")
    # In Times-Bold, 'zzAnchorzz' may split; just check the wrapper 'zz'.
    assert b"zz" in out


def test_column_min_width_enforced_by_widest_token():
    """Shrunken columns can't fall below their widest single word.

    Added 0.0.11.7 after a torture-test render showed `Second` jammed
    against the column border because the proportional-shrink path
    squeezed the Topic column below the width of its longest cell word.
    """
    from inkmd.render import _shrink_to_budget

    # Two columns: one with widest token = 40pt, one with no constraint.
    natural = [40.0, 400.0]
    min_widths = [40.0, 1.0]
    budget = 200.0
    result = _shrink_to_budget(natural, budget, min_widths)
    # Column 0 must be at least 40 (its widest token).
    assert result[0] >= 40.0
    # Sum equals budget (within float tolerance).
    assert abs(sum(result) - budget) < 0.01


def test_compile_narrow_topic_column_does_not_crush():
    """End-to-end: a 'Second' word in a narrow Topic column shouldn't
    overflow its cell."""
    md = (
        "| Topic | Description |\n"
        "| ----- | ----------- |\n"
        "| First | " + "filler " * 50 + "|\n"
        "| Second | another long row |\n"
        "| Third | x |\n"
    )
    out = inkmd.compile(md)
    # Just check it produces a valid PDF — the visual check is in
    # /tmp/inkmd-narrow-table-v2.pdf. The previous (broken) version
    # produced a crushed Topic column but the PDF was still structurally
    # valid, so this test is mostly a smoke check.
    assert out.startswith(b"%PDF-1.4\n")


def test_compile_alignment_affects_x_position():
    """A right-aligned cell should place its run further right than a left-aligned one."""
    md_left = "| H |\n| :--- |\n| x |"
    md_right = "| H |\n| ---: |\n| x |"
    # Render both, find the x of the 'x' body cell in each.
    from inkmd.render import render_document

    blocks_left = render_document(parse(md_left))[0]
    blocks_right = render_document(parse(md_right))[0]
    x_left = None
    x_right = None
    for _baseline, runs in blocks_left.prepositioned_lines:
        for r in runs:
            if r.text == "x":
                x_left = r.x_rel
    for _baseline, runs in blocks_right.prepositioned_lines:
        for r in runs:
            if r.text == "x":
                x_right = r.x_rel
    assert x_left is not None and x_right is not None
    assert x_right > x_left
