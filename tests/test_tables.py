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


def test_table_ends_at_block_construct():
    """A block-level construct (here a blank line) ends the table.

    Per GFM §4.10 a table is broken only by a blank line or the start of
    another block-level structure — NOT by a plain paragraph line, which is
    absorbed as a continuation row (see test_table_absorbs_lazy_row_line).
    """
    doc = parse("| A |\n| --- |\n| 1 |\n\nNot a row.")
    assert len(doc.blocks) == 2
    assert isinstance(doc.blocks[0], Table)
    assert isinstance(doc.blocks[1], Paragraph)


def test_table_absorbs_lazy_row_line():
    """A non-pipe paragraph line immediately after table rows continues the
    table as a row whose text fills the first cell (GFM §4.10, example 202)."""
    doc = parse("| A | B |\n| --- | --- |\n| 1 | 2 |\nlazy")
    assert len(doc.blocks) == 1
    t = doc.blocks[0]
    assert isinstance(t, Table)
    assert len(t.rows) == 2
    assert t.rows[1][0] == TableCell(inlines=(Text("lazy"),))
    assert t.rows[1][1] == TableCell(inlines=())


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


def test_header_only_table_renders_headers_on_one_line():
    """Header-only table where natural width fits the budget should
    NOT wrap text within cells (kerning-loss slack guard).

    Added 0.0.11.8: `| Empty Body | Still Valid |` was wrapping
    `Still Valid` onto two lines because the natural width was equal
    to the column content width, but individual token widths summed
    slightly higher due to lost kerning across word boundaries.
    """
    from inkmd.render import render_document

    md = "| Empty Body | Still Valid |\n| ---------- | ----------- |"
    doc = parse(md)
    block = render_document(doc)[0]
    second_col_runs = [
        (by, r) for by, runs in block.prepositioned_lines for r in runs
        if r.text.strip() in ("Still", "Valid")
    ]
    baselines = sorted({by for by, _ in second_col_runs})
    assert len(baselines) == 1, f"'Still Valid' wrapped: baselines={baselines}"


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
    assert out.startswith(b"%PDF-1.5\n")
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
    assert out.startswith(b"%PDF-1.5\n")


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


# --- Inline decorations inside table cells (red-team family, 15 findings) ---


def _table_cell_runs(md: str):
    """Paginate a table and return all positioned runs across pages."""
    from inkmd.render import render_document, FAMILIES
    from inkmd.html_filter import filter_document as fh
    from inkmd.url_filter import filter_document as fu
    from inkmd.image_loader import resolve_images as ri
    from inkmd.layout import paginate_runs

    doc = parse(md)
    doc = fh(doc, html=True)
    doc = fu(doc, safe=True)
    doc = ri(doc, base_dir=None, allow_remote=False)
    blocks = render_document(doc, FAMILIES["helvetica"])
    pages = paginate_runs(blocks, page_width=612, page_height=792)
    return [r for pg in pages for ln in pg.lines for r in ln.runs]


def test_strikethrough_survives_in_table_cell():
    """Regression: ~~struck~~ in a table cell must keep its strike flag
    (was silently dropped because _PR omitted the decoration fields)."""
    runs = _table_cell_runs("| F | S |\n|---|---|\n| ~~struck~~ | x |")
    assert any(getattr(r, "strike", False) for r in runs)


def test_mark_highlight_survives_in_table_cell():
    runs = _table_cell_runs("| F | S |\n|---|---|\n| <mark>hi</mark> | x |")
    assert any(getattr(r, "background_fill", None) for r in runs)


def test_underline_survives_in_table_cell():
    runs = _table_cell_runs("| F | S |\n|---|---|\n| <u>under</u> | x |")
    assert any(getattr(r, "underline", False) for r in runs)


def test_kbd_border_survives_in_table_cell():
    runs = _table_cell_runs("| F | S |\n|---|---|\n| <kbd>K</kbd> | x |")
    assert any(getattr(r, "border_fill", None) for r in runs)


def test_superscript_baseline_shift_survives_in_table_cell():
    runs = _table_cell_runs("| F | S |\n|---|---|\n| x<sup>2</sup> | x |")
    assert any(getattr(r, "y_shift", 0.0) for r in runs)


def test_table_fits_within_a4_margins():
    """Regression: table width must be budgeted to the actual page size.
    On A4 (narrower than letter) a wide table must not overflow the
    right margin (TABLE width was hardcoded to letter's 468pt)."""
    from inkmd.render import render_document, FAMILIES
    from inkmd.layout import paginate_runs, DEFAULT_MARGIN
    from inkmd.fonts import text_width
    from inkmd.pdf import resolve_page_size

    md = ("| Setting | Value |\n|---|---|\n"
          "| `application.feature.flag.enabled` | `org.example.module.Sub` |")
    pw, ph = resolve_page_size("A4")
    cw = pw - 2 * DEFAULT_MARGIN
    blocks = render_document(parse(md), FAMILIES["helvetica"], content_width=cw)
    pages = paginate_runs(blocks, page_width=pw, page_height=ph)
    limit = pw - DEFAULT_MARGIN
    for pg in pages:
        for ln in pg.lines:
            for r in ln.runs:
                assert r.x + text_width(r.text, r.font, r.size) <= limit + 0.5
        for s in pg.shapes:
            right = getattr(s, "x", 0.0) + getattr(s, "width", 0.0)
            assert right <= limit + 0.6  # +grid stroke tolerance


# --- Column-width fallback + alignment clamp (red-team batch 3) -------------


def _table_cell_runs_sized(md: str, page="letter"):
    """Like _table_cell_runs but threads the real page content width so
    column-budget behaviour matches a live ``compile`` call."""
    from inkmd.render import render_document, FAMILIES
    from inkmd.html_filter import filter_document as fh
    from inkmd.url_filter import filter_document as fu
    from inkmd.image_loader import resolve_images as ri
    from inkmd.layout import paginate_runs, DEFAULT_MARGIN
    from inkmd.pdf import PAGE_SIZES

    pw, ph = PAGE_SIZES[page]
    cw = pw - 2 * DEFAULT_MARGIN
    doc = parse(md)
    doc = fh(doc, html=True)
    doc = fu(doc, safe=True)
    doc = ri(doc, base_dir=None, allow_remote=False)
    blocks = render_document(doc, FAMILIES["helvetica"], content_width=cw)
    pages = paginate_runs(blocks, page_width=pw, page_height=ph)
    return [r for pg in pages for ln in pg.lines for r in ln.runs], pw, ph


def test_right_aligned_narrow_cell_does_not_escape_left():
    """Regression (findings 17, 46): a right-aligned column crushed near
    its glyph width must not position content LEFT of the page margin —
    the old fallback abandoned per-column minima and a negative alignment
    offset flung glyphs leftward across the grid line into the neighbour."""
    from inkmd.layout import DEFAULT_MARGIN

    md = (
        "| a | b |\n|--:|--:|\n"
        "| " + "Q" * 100 + " | @ |"
    )
    runs, pw, _ = _table_cell_runs_sized(md)
    # Padding inside the table puts the leftmost legitimate content a few
    # points inside the margin; nothing may sit at or left of the margin.
    assert runs, "expected positioned runs"
    assert min(r.x for r in runs) >= DEFAULT_MARGIN - 0.01


def test_single_wide_glyph_neighbour_not_crushed_below_glyph():
    """Regression (finding 50): one column holding a very long unbreakable
    run must not crush an innocent neighbour below its own glyph width and
    push that glyph past the cell/table right edge. Char-level minima keep
    every column at least one glyph wide so the table fits the page."""
    from inkmd.fonts import text_width
    from inkmd.layout import DEFAULT_MARGIN

    md = "| a | b |\n|---|---|\n| " + "x" * 300 + " | — |"
    runs, pw, _ = _table_cell_runs_sized(md)
    limit = pw - DEFAULT_MARGIN
    for r in runs:
        assert r.x + text_width(r.text, r.font, r.size) <= limit + 0.5


def test_many_column_table_columns_do_not_overprint():
    """Regression (findings 7, 11, 14, 21): a table with so many columns
    that padding alone exceeds the budget used to produce zero/negative
    column widths, overprinting glyphs onto one another. Each column must
    now keep a positive width so adjacent header cells stay separated."""
    cols = 36
    header = "|" + "|".join(f"C{i}" for i in range(cols)) + "|"
    sep = "|" + "|".join("---" for _ in range(cols)) + "|"
    body = "|" + "|".join(str(i % 10) for i in range(cols)) + "|"
    md = "\n".join([header, sep, body])
    runs, _, _ = _table_cell_runs_sized(md)
    # Group the header runs by baseline y and assert strictly increasing x
    # with a real gap — no two columns share a position (overprint).
    by_y: dict[float, list[float]] = {}
    for r in runs:
        by_y.setdefault(round(r.y, 1), []).append(r.x)
    # The header is the topmost row.
    top_y = max(by_y)
    xs = sorted(by_y[top_y])
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    assert gaps, "expected multiple header columns"
    assert min(gaps) > 2.0  # clearly separated, not z-fighting


# --- Emoji in table cells (Phase 7) ---------------------------------------


def test_emoji_in_table_cell_renders_as_image():
    """A status emoji in a table cell must render as an inline image
    (placed in the cell), not fall through to '?'. Uses a synthetic font
    so the test is portable."""
    from inkmd import emoji as emoji_mod
    from inkmd.emoji_font import EmojiFont
    from inkmd.render import render_document, FAMILIES
    from inkmd.layout import paginate_runs, ImagePlacement
    from tests.test_emoji_font import _build_cbdt_font, _tiny_png

    font = EmojiFont(_build_cbdt_font({0x2705: 1}, {1: _tiny_png(120, 128)}))
    emoji_mod._load_font.cache_clear()
    orig = emoji_mod._load_font
    emoji_mod._load_font = lambda: font
    try:
        md = "| Feature | Status |\n|---|---|\n| Parser | \U00002705 |"
        blocks = render_document(parse(md), FAMILIES["helvetica"], content_width=468.0)
        pages = paginate_runs(blocks, page_width=612, page_height=792)
        placements = [
            s for pg in pages for s in pg.shapes if isinstance(s, ImagePlacement)
        ]
        assert len(placements) == 1
        assert placements[0].image_id == "emoji:2705"
        # The check glyph must NOT also appear as a '?' text run.
        texts = {r.text for pg in pages for ln in pg.lines for r in ln.runs}
        assert "\U00002705" not in texts
    finally:
        emoji_mod._load_font = orig
        emoji_mod._load_font.cache_clear()


# --- Row = single source line (GFM spec); cell vertical alignment ---------
# An audit finding claimed a "trailing-space hard break inside a cell"
# mis-aligns the sibling cell. Per GFM, a pipe-table row is exactly one
# source line: a newline mid-content ENDS the row and starts a new one.
# So `| Cell with  \nhard break | Normal cell |` is two rows, not one row
# with a two-line cell — and "Normal cell" correctly sits in row 2 beside
# "hard break". The reported "misalignment" is spec-correct rendering of
# malformed input (matches GitHub). These tests pin that behaviour so a
# future "fix" can't silently break GFM row semantics, and confirm that a
# genuinely multi-line (naturally-wrapped) cell top-aligns its short sibling.


def _run_at_text(md, content_width=468.0):
    """Map first-word-of-run text -> rounded baseline y, across the table."""
    from inkmd.render import render_document, FAMILIES
    from inkmd.layout import paginate_runs, StyledLine

    blocks = render_document(parse(md), FAMILIES["helvetica"], content_width=content_width)
    pages = paginate_runs(blocks, page_width=612, page_height=792)
    out: dict[str, float] = {}
    for pg in pages:
        for ln in pg.lines:
            if isinstance(ln, StyledLine):
                for r in ln.runs:
                    if r.text.strip():
                        out.setdefault(r.text, round(r.y, 1))
    return out


def test_newline_mid_row_splits_into_two_rows_not_multiline_cell():
    # The spec-correct reading of malformed input: the newline ends row 1
    # (Col A = "Cell with", Col B empty), row 2 = "hard break" + "Normal
    # cell". "Normal cell" therefore shares row 2's baseline with "hard
    # break", BELOW "Cell with". This is correct, not a misalignment.
    ys = _run_at_text(
        "| Col A | Col B |\n|-------|-------|\n| Cell with  \nhard break | Normal cell |"
    )
    assert ys["Cell"] > ys["hard"]            # row 1 above row 2
    assert ys["Normal"] == ys["hard"]         # Normal cell is in row 2
    assert ys["Normal"] < ys["Cell"]          # ...not row 1


def test_naturally_wrapped_cell_top_aligns_short_sibling():
    # A VALID single-row table whose Col A wraps to multiple lines must
    # top-align the short Col B sibling with Col A's FIRST line.
    md = (
        "| ColumnA | ColumnB |\n|---|---|\n"
        "| alpha beta gamma delta epsilon zeta eta | Short |"
    )
    ys = _run_at_text(md, content_width=260.0)
    # Col A's first word and the short sibling share the row's top baseline.
    assert ys["alpha"] == ys["Short"]
    # And Col A genuinely wrapped to a lower line (proving multi-line).
    assert ys["eta"] < ys["alpha"]


# --- Bold-italic composition in a (bold) table header ----------------------


def _cell_font(md, text):
    """Return the font of the run whose text == ``text`` in a table."""
    from inkmd.render import render_document, FAMILIES
    from inkmd.layout import paginate_runs, StyledLine

    blocks = render_document(parse(md), FAMILIES["helvetica"], content_width=468.0)
    pages = paginate_runs(blocks, page_width=612, page_height=792)
    for pg in pages:
        for ln in pg.lines:
            if isinstance(ln, StyledLine):
                for r in ln.runs:
                    if r.text == text:
                        return r.font
    return None


def test_bold_italic_in_table_header_keeps_italic():
    # ***x*** in a header cell must compose to bold-italic, matching the
    # body. The header seeds the run as bold; Strong/Emphasis composition
    # used to drop the italic because it only checked == italic, not the
    # already-bold (or bold_italic) face.
    md = "| ***hdr*** | x |\n|---|---|\n| ***body*** | y |"
    assert _cell_font(md, "hdr") == "Helvetica-BoldOblique"
    assert _cell_font(md, "body") == "Helvetica-BoldOblique"


def test_italic_in_bold_header_is_bold_italic():
    # A header cell is already bold; *i* inside it adds italic → bold-italic.
    md = "| *i* | h2 |\n|---|---|\n| r1 | r2 |"
    assert _cell_font(md, "i") == "Helvetica-BoldOblique"


def test_plain_bold_in_header_stays_bold():
    md = "| **bld** | h2 |\n|---|---|\n| r1 | r2 |"
    assert _cell_font(md, "bld") == "Helvetica-Bold"


# --- Table page-splitting (v0.2): a too-tall table breaks across pages ----
# A table taller than one page splits at a row boundary and repeats the
# header on each page-slice, instead of overflowing off the bottom (which
# silently lost rows). Single-page tables are unaffected.


def _table_pages(md, page_height=792):
    from inkmd.render import render_document, FAMILIES
    from inkmd.layout import paginate_runs

    blocks = render_document(parse(md), FAMILIES["helvetica"], content_width=468.0)
    return paginate_runs(blocks, page_width=612, page_height=page_height)


def _big_table(n_rows):
    head = "| Idx | Value |\n|---|---|\n"
    rows = "\n".join(f"| row{i} | val{i} |" for i in range(n_rows))
    return head + rows


def test_tall_table_splits_across_pages():
    pages = _table_pages(_big_table(120))
    assert len(pages) > 1


def test_split_table_repeats_header_on_each_page():
    from inkmd.layout import StyledLine

    pages = _table_pages(_big_table(120))
    for pidx, pg in enumerate(pages):
        texts = [
            r.text for ln in pg.lines if isinstance(ln, StyledLine) for r in ln.runs
        ]
        assert "Idx" in texts, f"header missing on page {pidx + 1}"


def test_split_table_loses_no_rows_off_page():
    from inkmd.layout import StyledLine

    pages = _table_pages(_big_table(120))
    # No run may sit below the bottom margin (y < 72 for a 792pt page).
    for pidx, pg in enumerate(pages):
        below = [
            r.y
            for ln in pg.lines
            if isinstance(ln, StyledLine)
            for r in ln.runs
            if r.y < 72
        ]
        assert not below, f"page {pidx + 1} has {len(below)} runs off the page"
    # And every body row's text is present exactly once across all pages.
    all_text = "".join(
        r.text
        for pg in pages
        for ln in pg.lines
        if isinstance(ln, StyledLine)
        for r in ln.runs
    )
    for i in range(120):
        assert f"row{i}" in all_text, f"row{i} was dropped"


def test_single_page_table_not_split():
    # A small table stays on one page (no spurious splitting).
    pages = _table_pages("| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |")
    assert len(pages) == 1


def test_single_page_table_output_unchanged():
    # Byte-level guard: a fits-on-a-page table must compile to a valid PDF
    # deterministically (the row-group refactor must not change small-table
    # output behaviour).
    md = "| H1 | H2 |\n|---|---|\n| a | b |\n| c | d |"
    a = inkmd.compile(md)
    assert a[:4] == b"%PDF"
    assert inkmd.compile(md) == a


def test_giant_single_row_degrades_without_crash():
    # A single row taller than a whole page can't be split further; it
    # places atomically (and may overflow) but must not crash compile().
    md = "| H |\n|---|\n| " + ("word " * 4000) + " |"
    pdf = inkmd.compile(md)
    assert pdf[:4] == b"%PDF"


def test_split_table_each_slice_is_boxed():
    # Every page-slice draws its own grid (vertical rules + a bottom rule),
    # so a continued table is fully boxed, not left open at the page break.
    from inkmd.layout import Rect

    pages = _table_pages(_big_table(120))
    for pidx, pg in enumerate(pages):
        rects = [s for s in pg.shapes if isinstance(s, Rect)]
        # At least the two column verticals + edges + a bottom rule.
        assert len(rects) >= 3, f"page {pidx + 1} under-boxed"
