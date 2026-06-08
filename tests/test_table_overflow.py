"""Wide-table fitting: the table_overflow knob and lossless panel-wrap (v0.5 S6).

S6 makes inkmd's default for a too-wide table to WRAP it into stacked
panels (lossless: nothing shrunk or clipped, column 0 repeated as the key
column), and adds a public ``table_overflow`` knob with four modes:

- ``"wrap"`` (default): panel-wrap.
- ``"shrink"``: the pre-0.5 path (shrink proportionally, overflow right).
- ``"warn"``: ``"shrink"`` plus one ``TableOverflowWarning``.
- ``"error"``: raise ``TableOverflowError`` on a non-fitting table.

The prime directive: a table that FITS renders byte-identically in every
mode (the default flips to ``"wrap"`` but that only changes OVERFLOWING
tables). The frozen validation baseline proves byte-identity against real
0.4 output across the corpus; these tests pin the new behaviour and the
knob plumbing.
"""

from __future__ import annotations

import re
import warnings

import pytest

import inkmd
from inkmd import LayoutConfig, TableOverflowError, TableOverflowWarning
from inkmd.parser import parse
from inkmd.ast import Table
from inkmd.layout import DEFAULT_MARGIN, Rect, StyledLine, paginate_runs
from inkmd.pdf import resolve_page_size
from inkmd.render import (
    BODY_SIZE,
    FAMILIES,
    TABLE_CELL_PADDING_X,
    TABLE_CONTINUED_LABEL,
    _cap_height_floored_mins,
    _partition_columns,
    _render_inline,
    _widest_token_width,
    emoji_box,
    render_document,
    text_width,
)


LETTER_CONTENT_WIDTH = 468.0  # 8.5in - 2*1in margins
LANDSCAPE_LETTER_CONTENT_WIDTH = 648.0  # 11in - 2*1in margins
LETTER_USABLE_HEIGHT = 648.0  # 11in - 2*1in margins (page height - 2*margin)


# --- Helpers --------------------------------------------------------------


def _table_md(headers, rows):
    """Build a GFM pipe-table from header names + a list of row value-lists."""
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return head + "\n" + sep + "\n" + body + "\n"


def _wide_table_md(n_cols=12, n_rows=3, cell_prefix="datum"):
    """A table whose NATURAL width overflows letter. In shrink/warn modes it
    stays one block (columns squeezed, cells wrapped). NOTE: at the default
    12 medium-token columns its READABLE-floor minimums exceed the budget,
    so wrap mode DOES panel it (2 panels); the wrap-mode tests that need a
    table guaranteed not to panel build their own short-token fixtures, and
    ``_panel_forcing_table_md`` exists for tests that want many panels."""
    headers = [f"Heading{i}" for i in range(n_cols)]
    rows = [
        [f"{cell_prefix}-{r}-{i}" for i in range(n_cols)] for r in range(n_rows)
    ]
    return _table_md(headers, rows)


def _panel_forcing_table_md(n_cols=30, n_rows=2):
    """A table that overflows EVEN AT one character per column, so panels are
    the only lossless fit. Padding alone is ``n_cols * 12pt`` on letter, and
    each short column's minimum is one glyph wide, so ~30 columns push
    ``sum(min_widths)`` past the 468pt content budget. Short single-token
    cells keep the fixture unambiguous (every cell is one unbreakable token)."""
    headers = [f"C{i}" for i in range(n_cols)]
    rows = [[f"r{r}v{i % 10}" for i in range(n_cols)] for r in range(n_rows)]
    return _table_md(headers, rows)


def _wide_cell_panel_table_md(n_cols=30, n_rows=3, cell_len=20):
    """Like _panel_forcing_table_md but with WIDE no-space cells (default 20
    chars, wider than the 8-char panel floor), so a panel packs more columns
    than fit at natural width and must SHRINK them to fit. Column 0 is a unique
    short label; data columns are a single ``cell_len``-char token."""
    headers = ["key"] + [f"h{i}" for i in range(1, n_cols)]
    token = "a" * cell_len
    rows = [["K%d" % r] + [token] * (n_cols - 1) for r in range(n_rows)]
    return _table_md(headers, rows)


def _natural_and_min(md, content_width=LETTER_CONTENT_WIDTH):
    """Compute (natural_sum, min_widths_sum, content_budget) for a table the
    way _render_table does, so a test can PROVE which path its fixture takes.
    """
    fam = FAMILIES["helvetica"]
    doc = parse(md)
    table = next(b for b in doc.blocks if isinstance(b, Table))
    n = len(table.headers)

    def cell_runs(cell, bold):
        font = fam.bold if bold else fam.regular
        out = []
        for inl in cell.inlines:
            out.extend(_render_inline(inl, fam, font=font, size=BODY_SIZE))
        return out

    def runs_nat(runs):
        total = 0.0
        for r in runs:
            total += (
                emoji_box(r.size, r.emoji.aspect)[0]
                if r.emoji is not None
                else text_width(r.text, r.font, r.size)
            )
        return total

    header_runs = [cell_runs(c, True) for c in table.headers]
    body_runs = [[cell_runs(c, False) for c in row] for row in table.rows]
    natural = [0.0] * n
    for i, rr in enumerate(header_runs):
        natural[i] = max(natural[i], runs_nat(rr))
    for row in body_runs:
        for i, rr in enumerate(row):
            natural[i] = max(natural[i], runs_nat(rr))
    min_widths = [_widest_token_width(header_runs[i], body_runs, i) for i in range(n)]
    content_budget = content_width - n * 2 * TABLE_CELL_PADDING_X
    return sum(natural), sum(min_widths), content_budget


def _floor_min_sum(md, floor_width, content_width=LETTER_CONTENT_WIDTH):
    """Sum of per-column min(natural, floor_width) -- the quantity the
    shrink-vs-panel gate compares against the content budget."""
    fam = FAMILIES["helvetica"]
    table = next(b for b in parse(md).blocks if isinstance(b, Table))
    n = len(table.headers)

    def cell_runs(cell, bold):
        font = fam.bold if bold else fam.regular
        out = []
        for inl in cell.inlines:
            out.extend(_render_inline(inl, fam, font=font, size=BODY_SIZE))
        return out

    def runs_nat(runs):
        return sum(
            emoji_box(r.size, r.emoji.aspect)[0]
            if r.emoji is not None
            else text_width(r.text, r.font, r.size)
            for r in runs
        )

    natural = [0.0] * n
    for i, c in enumerate(table.headers):
        natural[i] = max(natural[i], runs_nat(cell_runs(c, True)))
    for row in table.rows:
        for i, c in enumerate(row):
            natural[i] = max(natural[i], runs_nat(cell_runs(c, False)))
    return sum(min(w, floor_width) for w in natural)


def _paginate(md, page="letter", orientation="portrait"):
    """Render + paginate a markdown string to Page records, so a test can
    inspect the actually-placed lines and shapes (where the continuation
    label now lives -- the paginator draws it, not the renderer)."""
    pw, ph = resolve_page_size(page, orientation)
    content_width = pw - 2 * DEFAULT_MARGIN
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=content_width
    )
    return paginate_runs(blocks, page_width=pw, page_height=ph, margin=DEFAULT_MARGIN)


def _panels(blocks):
    """The prepositioned table blocks (one per panel) among rendered blocks."""
    return [b for b in blocks if getattr(b, "prepositioned_table", None) is not None]


def _panel_header_texts(panel):
    """All text runs across a panel's header group lines, in order."""
    out = []
    for _baseline, runs in panel.prepositioned_table["header"]["lines"]:
        for r in runs:
            out.append(r.text)
    return out


def _all_cell_text(blocks):
    """Every text fragment placed by any panel (header + body)."""
    out = []
    for b in _panels(blocks):
        meta = b.prepositioned_table
        for group in (meta["header"],) + tuple(meta["rows"]):
            for _baseline, runs in group["lines"]:
                for r in runs:
                    out.append(r.text)
    return out


def _pdf_page_count(pdf: bytes) -> int:
    """Count /Type /Page objects (not the /Pages tree node)."""
    # Page objects are "/Type /Page " (trailing space); the tree is "/Type /Pages".
    return pdf.count(b"/Type /Page ")


def _assert_pdf_structurally_valid(pdf: bytes):
    """Cheap stdlib-only structural sanity for a produced PDF (no external
    parser). Mirrors the checks in test_pdf_emission.py: a header, an xref
    section, a startxref that lands on it, the %%EOF trailer, and a page tree
    whose /Count matches the number of /Type /Page objects. This is "valid
    file", separate from "lossless content" -- a truncated file can still
    start with %PDF, so we check the trailer + xref + page-count consistency.
    """
    assert pdf[:5] == b"%PDF-", "missing PDF header"
    assert b"\nxref\n" in pdf, "missing xref section"
    assert pdf.rstrip(b"\n").endswith(b"%%EOF"), "missing %%EOF trailer"
    m = re.search(rb"startxref\n(\d+)\n", pdf)
    assert m is not None, "missing startxref"
    assert pdf[int(m.group(1)):int(m.group(1)) + 4] == b"xref", (
        "startxref does not land on the xref keyword"
    )
    # Page-tree consistency: the Pages node's /Count equals the number of
    # actual Page objects emitted (no silent page capping).
    page_objs = _pdf_page_count(pdf)
    assert page_objs > 0, "no page objects emitted"
    cm = re.search(rb"/Type /Pages /Kids \[[^\]]*\] /Count (\d+)", pdf)
    assert cm is not None, "missing /Type /Pages /Count"
    assert int(cm.group(1)) == page_objs, (
        f"page tree /Count {int(cm.group(1))} != {page_objs} Page objects"
    )


def _torture_table_md(n_cols, n_rows, cell_len, torture_char="a"):
    """Build the adversary table for the lossless existence proof.

    Column 0 holds a UNIQUE label per row (``K0``..``K{n_rows-1}``) that does
    NOT contain the torture character; columns 1..n-1 each hold a single
    ``torture_char * cell_len`` token with NO whitespace (maximally
    unbreakable, forcing char-by-char wrapping). This layout makes the
    lossless invariant exact AND panel-safe: the panel path repeats column 0
    in every panel, so torture content lives only in the never-repeated
    columns 1..n-1 -- the placed torture-char count is therefore exactly
    ``(n_cols - 1) * n_rows * cell_len`` no matter how many panels result,
    while every one of the ``n_rows`` distinct col-0 labels must still appear
    (proving the key-column repetition drops nothing either).
    """
    headers = ["key"] + [f"h{i}" for i in range(1, n_cols)]
    token = torture_char * cell_len
    rows = [[f"K{r}"] + [token] * (n_cols - 1) for r in range(n_rows)]
    return _table_md(headers, rows)


def _placed_char_count(blocks, char):
    """Total occurrences of ``char`` across every placed run in every block."""
    total = 0
    for b in blocks:
        meta = getattr(b, "prepositioned_table", None)
        if meta is None:
            continue
        for group in (meta["header"],) + tuple(meta["rows"]):
            for _baseline, runs in group["lines"]:
                for r in runs:
                    total += r.text.count(char)
    return total


def _placed_text_joined(blocks):
    """All placed run text concatenated, in placement order. Used to check a
    label survived even when it char-wraps across lines (a shrunk column 0
    splits ``K7`` into ``K`` + ``7`` on separate lines, so a per-run match
    would miss it -- a substring check on the joined text does not)."""
    parts = []
    for b in blocks:
        meta = getattr(b, "prepositioned_table", None)
        if meta is None:
            continue
        for group in (meta["header"],) + tuple(meta["rows"]):
            for _baseline, runs in group["lines"]:
                for r in runs:
                    parts.append(r.text)
    return "".join(parts)


def _content_stream_literals(line: bytes) -> list[bytes]:
    """All ``(...)`` literal strings in one content-stream line, unescaped.

    Handles the escapes the emitter produces (``\\(``, ``\\)``, ``\\\\``) plus
    octal escapes for robustness. Returns raw WinAnsi bytes per literal.
    """
    out: list[bytes] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i:i + 1] != b"(":
            i += 1
            continue
        i += 1
        buf = bytearray()
        depth = 1
        while i < n and depth > 0:
            c = line[i:i + 1]
            if c == b"\\":
                nxt = line[i + 1:i + 2]
                if nxt.isdigit():
                    j = i + 1
                    digits = b""
                    while (j < n and len(digits) < 3
                           and line[j:j + 1].isdigit()):
                        digits += line[j:j + 1]
                        j += 1
                    buf.append(int(digits, 8))
                    i = j
                else:
                    mapping = {b"n": b"\n", b"r": b"\r", b"t": b"\t",
                               b"b": b"\b", b"f": b"\f"}
                    buf += mapping.get(nxt, nxt)
                    i += 2
                continue
            if c == b"(":
                depth += 1
            elif c == b")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            buf += c
            i += 1
        out.append(bytes(buf))
    return out


def _pdf_text_ops_by_page(pdf: bytes):
    """Per page, every placed text run as ``(x, y, text)`` parsed from the
    REAL content-stream bytes of the produced PDF.

    This reads the actual output, not renderer internals: streams are
    uncompressed, every run is positioned by an absolute ``1 0 0 1 x y Tm``
    and shown by ``(..) Tj`` or ``[..] TJ`` (kerned). The y is the run's
    baseline in page coordinates (origin bottom-left). Counting placed
    characters at the blocks layer cannot see WHERE glyphs land; this can,
    which is the whole point (a glyph placed below the media box is in the
    content stream but invisible to every reader). Assumes base-14 fonts
    (no ``<..> Tj`` hex runs) and text-only streams, true for every fixture
    in this file; fails loudly if a hex run shows up.
    """
    streams: dict[int, bytes] = {}
    for m in re.finditer(rb"(?m)^(\d+) 0 obj\n(.*?)\nendobj", pdf, re.DOTALL):
        sm = re.search(rb"stream\n(.*)\nendstream", m.group(2), re.DOTALL)
        if sm is not None:
            streams[int(m.group(1))] = sm.group(1)
    pages = []
    for m in re.finditer(rb"/Type /Page /Parent .*?/Contents (\d+) 0 R", pdf):
        ops: list[tuple[float, float, str]] = []
        x = y = 0.0
        for line in streams[int(m.group(1))].split(b"\n"):
            tm = re.match(rb"^1 0 0 1 (-?[\d.]+) (-?[\d.]+) Tm$", line)
            if tm is not None:
                x, y = float(tm.group(1)), float(tm.group(2))
                continue
            if line.endswith(b"> Tj"):
                raise AssertionError(
                    "embedded-font hex run in content stream; this helper "
                    "only decodes base-14 literal strings"
                )
            if line.endswith(b" Tj") or line.endswith(b"] TJ"):
                text = b"".join(_content_stream_literals(line)).decode(
                    "latin-1"
                )
                ops.append((x, y, text))
        pages.append(ops)
    return pages


def _assert_text_ops_on_page(pages, page_height=792.0, page_width=612.0,
                             margin=DEFAULT_MARGIN, eps=2.0):
    """Every placed run's baseline lies on the visible page: y inside the
    media box (hard) and within the margins give or take a small epsilon,
    and the run's start x inside the media box (S6g: a panel drawn wider
    than the page starts runs PAST the right edge, invisible). This is the
    assertion the older adversary tests were missing -- they counted placed
    characters without checking the glyphs land where a reader can see
    them."""
    for pi, ops in enumerate(pages):
        assert ops, f"page {pi} placed no text at all"
        for x, y, text in ops:
            assert 0.0 <= y <= page_height, (
                f"page {pi}: run at y={y:.1f} is outside the media box "
                f"(invisible): {text[:40]!r}"
            )
            assert margin - eps <= y <= page_height - margin + eps, (
                f"page {pi}: run baseline y={y:.1f} is outside the margins: "
                f"{text[:40]!r}"
            )
            assert 0.0 <= x <= page_width, (
                f"page {pi}: run starts at x={x:.1f}, outside the media "
                f"box (invisible): {text[:40]!r}"
            )


def _pdf_rects_by_page(pdf: bytes):
    """Per page, every filled rectangle as ``(x, y, w, h)`` parsed from the
    real content streams (the ``x y w h re f`` operator the emitter writes
    for grid rules and tint fills). The rects bound the table exactly --
    the outermost vertical rule IS the table's right edge -- so they are
    the ground truth for whether a table stayed within the margins."""
    streams: dict[int, bytes] = {}
    for m in re.finditer(rb"(?m)^(\d+) 0 obj\n(.*?)\nendobj", pdf, re.DOTALL):
        sm = re.search(rb"stream\n(.*)\nendstream", m.group(2), re.DOTALL)
        if sm is not None:
            streams[int(m.group(1))] = sm.group(1)
    pages = []
    for m in re.finditer(rb"/Type /Page /Parent .*?/Contents (\d+) 0 R", pdf):
        rects: list[tuple[float, float, float, float]] = []
        for line in streams[int(m.group(1))].split(b"\n"):
            rm = re.match(
                rb"^(-?[\d.]+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) re f$", line
            )
            if rm is not None:
                rects.append(tuple(float(g) for g in rm.groups()))
        pages.append(rects)
    return pages


def _assert_rects_within_right_margin(rect_pages, page_width=612.0,
                                      margin=DEFAULT_MARGIN, eps=1.0):
    """No grid/tint rect's right edge passes the right margin (S6g hard
    invariant for wrap mode: ``table_width <= content_budget``, so the
    outermost vertical rule lands at most half a grid width past the
    margin, well inside ``eps``)."""
    for pi, rects in enumerate(rect_pages):
        for x, y, w, h in rects:
            assert x + w <= page_width - margin + eps, (
                f"page {pi}: rect right edge {x + w:.1f} passes the right "
                f"margin ({page_width - margin:.0f}); the table bleeds off "
                f"the page"
            )


def _joined_pdf_text(pages) -> str:
    """All placed run text across all pages, concatenated in placement
    order (page by page, emission order within a page)."""
    return "".join(t for ops in pages for _x, _y, t in ops)


# --- Partition helper -----------------------------------------------------


def test_partition_groups_repeat_key_column():
    # Five equal-width columns, budget only fits two data columns per panel.
    # Floor is high enough (50) that columns count at their natural 50 width.
    natural = [50.0] * 5
    # content_width chosen so a panel of [key, c] (2 cols) fits but [key,c,c2]
    # (3 cols) does not. padding 6 each side -> per col 50 + 12 = 62.
    groups = _partition_columns(
        natural, content_width=130.0, padding_x=6.0, floor_width=50.0
    )
    assert groups is not None
    # Every group leads with column 0 (the key column).
    for g in groups:
        assert g[0] == 0
    # Groups partition columns 1..4 with col 0 repeated.
    data_cols = []
    for g in groups:
        data_cols.extend(g[1:])
    assert data_cols == [1, 2, 3, 4]


def test_partition_floor_packs_more_columns_than_natural():
    # The whole point of the floor: a wide column counts at the floor, not its
    # natural width, so more columns fit per panel. 10 columns of natural 100;
    # at natural width few fit, at a floor of 20 many more do -> fewer groups.
    natural = [100.0] * 10
    at_natural = _partition_columns(
        natural, content_width=468.0, padding_x=6.0, floor_width=float("inf")
    )
    at_floor = _partition_columns(
        natural, content_width=468.0, padding_x=6.0, floor_width=20.0
    )
    assert at_natural is not None and at_floor is not None
    assert len(at_floor) < len(at_natural)


def test_partition_single_column_returns_none():
    # A 1-column table has no data column to pair with the key -> tier 3.
    assert _partition_columns(
        [500.0], content_width=468.0, padding_x=6.0, floor_width=54.0
    ) is None


def test_partition_floored_monster_column_now_pairs():
    # Under flooring a column wider than the page is NO LONGER un-pairable: it
    # counts at the floor (it will be shrunk + cell-wrapped in the panel). So a
    # col 0 + 900pt col 1 with a normal ~54pt floor pairs fine (not tier 3).
    natural = [40.0, 900.0, 40.0]
    groups = _partition_columns(
        natural, content_width=468.0, padding_x=6.0, floor_width=54.0
    )
    assert groups is not None


def test_partition_terminates_on_many_columns():
    # A defensive check that packing always terminates and covers every column.
    natural = [30.0] * 40
    groups = _partition_columns(
        natural, content_width=468.0, padding_x=6.0, floor_width=54.0
    )
    assert groups is not None
    seen = []
    for g in groups:
        assert g[0] == 0
        seen.extend(g[1:])
    assert seen == list(range(1, 40))


# --- wrap: lossless panel behaviour ---------------------------------------
#
# Panels are the LAST RESORT: wrap mode only splits a table into panels when
# it overflows the page EVEN AT one character per column (sum(min_widths) >
# content_budget). A handful of normal-token columns shrink-and-wrap onto one
# strip instead (see the regression section below). So the panel fixtures
# below use ~30 columns, and each panel test asserts its fixture genuinely
# reaches the panel path by checking min_sum > budget.


def test_panel_forcing_fixture_actually_reaches_panel_path():
    # Pin the precondition the rest of this section relies on: the fixture
    # overflows even at one char per column, so it MUST panel (not shrink-wrap).
    md = _panel_forcing_table_md(n_cols=30, n_rows=2)
    natural_sum, min_sum, budget = _natural_and_min(md)
    assert min_sum > budget, (
        f"fixture must overflow at min widths to reach panels: "
        f"min_sum={min_sum:.0f} budget={budget:.0f}"
    )


def test_wide_table_wrap_produces_multiple_panels():
    md = _panel_forcing_table_md(n_cols=30, n_rows=2)
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    panels = _panels(blocks)
    assert len(panels) >= 2, "a 30-col un-fittable table should wrap into >= 2 panels"


def test_wrap_repeats_key_column_header_more_than_once():
    md = _panel_forcing_table_md(n_cols=30, n_rows=2)
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    # Column 0's header text "C0" appears once per panel.
    all_headers = []
    for p in _panels(blocks):
        all_headers.extend(_panel_header_texts(p))
    assert all_headers.count("C0") >= 2


def test_wrap_emits_continued_marker_on_later_panels():
    md = _panel_forcing_table_md(n_cols=30, n_rows=2)
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    panels = _panels(blocks)
    assert len(panels) >= 2
    # The marker now lives ABOVE the table box (drawn by the paginator), not in
    # the header group. The meta carries the signal: the first panel has no
    # label, every later panel does.
    assert panels[0].prepositioned_table["continued_label"] is None
    for p in panels[1:]:
        spec = p.prepositioned_table["continued_label"]
        assert spec is not None
        assert spec["text"] == TABLE_CONTINUED_LABEL
    # And the header group no longer contains the marker text.
    for p in panels:
        assert TABLE_CONTINUED_LABEL not in _panel_header_texts(p)


def test_continued_marker_is_placed_once_per_continuation_panel():
    # After pagination, the "(continued)" label appears exactly once per
    # continuation panel (panels 2..N), as a placed StyledLine -- not per page
    # slice, not on the first panel.
    md = _panel_forcing_table_md(n_cols=30, n_rows=2)
    pages = _paginate(md)
    n_labels = sum(
        1
        for pg in pages
        for ln in pg.lines
        if isinstance(ln, StyledLine)
        for r in ln.runs
        if r.text == TABLE_CONTINUED_LABEL
    )
    # A 30-col table makes 3 panels -> 2 continuation panels -> 2 labels.
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    n_continuation = sum(
        1
        for b in _panels(blocks)
        if b.prepositioned_table["continued_label"] is not None
    )
    assert n_labels == n_continuation >= 2


def test_continued_marker_not_crossed_by_grid_lines():
    # The bug this fix closes: the label was folded into the header box, so the
    # table's grid rules (the thin column separators and the header's top rule)
    # ran through the word. Now the label sits in the clear gap ABOVE the box.
    # Assert geometrically that no THIN grid rule (a separator, not the header
    # background tint) vertically overlaps the label's glyph band at the
    # label's x-range, on any page.
    md = _panel_forcing_table_md(n_cols=30, n_rows=2)
    pages = _paginate(md)
    grid_w = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    # grid rule thickness is the table's grid_width (~0.5pt); read it off a panel.
    panel = next(b for b in grid_w if getattr(b, "prepositioned_table", None))
    rule_w = panel.prepositioned_table["grid_width"]

    checked = 0
    for pg in pages:
        label_runs = [
            r
            for ln in pg.lines
            if isinstance(ln, StyledLine)
            for r in ln.runs
            if r.text == TABLE_CONTINUED_LABEL
        ]
        if not label_runs:
            continue
        # A grid rule is a Rect that is thin in one dimension (~rule_w). The
        # header background tint is wide AND tall, so it is excluded.
        rules = [
            s
            for s in pg.shapes
            if isinstance(s, Rect)
            and (s.width <= rule_w + 0.1 or s.height <= rule_w + 0.1)
        ]
        for lr in label_runs:
            # Label glyph band: baseline up to the ascent, plus a descender
            # margin below the baseline.
            top = lr.y + lr.size
            bot = lr.y - lr.size * 0.3
            lx0 = lr.x
            lx1 = lr.x + text_width(lr.text, lr.font, lr.size)
            for rect in rules:
                ry0 = rect.y
                ry1 = rect.y + rect.height
                rx0 = rect.x
                rx1 = rect.x + rect.width
                y_overlap = ry1 > bot and ry0 < top
                x_overlap = rx1 > lx0 and rx0 < lx1
                assert not (y_overlap and x_overlap), (
                    "a grid rule crosses the (continued) label: "
                    f"label y[{bot:.1f},{top:.1f}] x[{lx0:.1f},{lx1:.1f}] "
                    f"vs rule y[{ry0:.1f},{ry1:.1f}] x[{rx0:.1f},{rx1:.1f}]"
                )
                checked += 1
    assert checked > 0, "expected to compare the label against >= 1 grid rule"


def test_wrap_drops_no_cell_text():
    # Every header + body cell's text must be present somewhere in the panels.
    headers = [f"C{i}" for i in range(30)]
    rows = [[f"r{r}v{i}" for i in range(30)] for r in range(2)]
    md = _table_md(headers, rows)
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    assert len(_panels(blocks)) >= 2
    placed = "".join(_all_cell_text(blocks))
    for h in headers:
        assert h in placed
    for row in rows:
        for cell in row:
            assert cell in placed


def test_wrap_is_lossless_each_panel_within_budget():
    # The lossless proxy: every panel's table_width fits the content width,
    # i.e. each panel renders at natural widths and still fits by construction.
    md = _panel_forcing_table_md(n_cols=30, n_rows=2)
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    panels = _panels(blocks)
    assert len(panels) >= 2
    for p in panels:
        assert p.prepositioned_table["table_width"] <= LETTER_CONTENT_WIDTH + 0.5


def test_wrap_panels_are_shrunk_to_fit_not_overflowing():
    # Panels pack at a readable floor and are then shrunk to fit, so every
    # panel's full width (incl. all column widths + padding) stays within the
    # content width -- columns wrap their cells rather than overflowing the
    # right edge. Use wide (20-char) no-space cells so the floored packing puts
    # more columns in a panel than fit at natural width, forcing the shrink.
    md = _wide_cell_panel_table_md(n_cols=30, n_rows=3, cell_len=20)
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    panels = _panels(blocks)
    assert len(panels) >= 2
    for p in panels:
        meta = p.prepositioned_table
        assert meta["table_width"] <= LETTER_CONTENT_WIDTH + 0.5, (
            f"panel overflows: table_width={meta['table_width']:.1f} "
            f"> content_width={LETTER_CONTENT_WIDTH}"
        )
        # The rightmost column's right edge (table_width) is the box edge; the
        # last col_x plus its width must equal table_width (panel is closed).
        assert meta["col_x"][0] == 0.0


def _panel_count(md, **kw):
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH, **kw
    )
    return len(_panels(blocks))


def test_floor_packing_makes_far_fewer_panels_than_natural_packing():
    # The core fix: a 30-col wide-cell table used to make ~15 panels (2 data
    # cols each, packed at natural width). With the readable floor it packs
    # many more columns per panel, so far fewer panels. Assert the default is
    # well under the old natural-packing count.
    md = _wide_cell_panel_table_md(n_cols=30, n_rows=2, cell_len=20)
    n_default = _panel_count(md)  # default table_panel_min_chars=8
    # Reproduce the OLD natural-width packing count via a huge floor (so the
    # floor never bites and columns pack at natural width).
    n_natural = _panel_count(md, table_panel_min_chars=10_000)
    assert n_natural >= 12, f"expected ~15 natural-pack panels, got {n_natural}"
    assert n_default <= 6, f"expected <= 6 floor-pack panels, got {n_default}"
    assert n_default < n_natural


def _panel_widest_data_col_content(panel):
    """The widest data-column (col >= 1) content width in a panel, in points."""
    col_x = panel.prepositioned_table["col_x"]
    table_width = panel.prepositioned_table["table_width"]
    edges = list(col_x) + [table_width]
    widest = 0.0
    for j in range(1, len(col_x)):  # skip col 0 (the key column)
        content = (edges[j + 1] - edges[j]) - 2 * TABLE_CELL_PADDING_X
        widest = max(widest, content)
    return widest


# --- the shrink-vs-panel GATE: gate on the readable floor, not 1 char -------
#
# Fix (d): a dozen-plus columns can squeak under the page at one character per
# column (padding eats most of the page), so the old gate
# (sum(widest-char-min) <= budget -> shrink) crushed e.g. a 24-col table onto
# one strip with every column one glyph wide -- lossless but unreadable. The
# gate now uses the same readable floor that governs panel packing
# (sum(min(natural, floor)) <= budget), so a table that can't fit READABLY
# panels into strips instead of crushing.


def test_many_column_table_panels_instead_of_crushing_to_one_char():
    # A dozen columns of moderately-wide content: overflows at natural, FITS at
    # one char per column (so the old gate shrink-wrapped it to ~1 char each),
    # but does NOT fit at the readable floor -> now panels into readable strips.
    n_cols = 12
    headers = ["key"] + [f"Metric{i}" for i in range(1, n_cols)]
    rows = [["K%d" % r] + ["value%02d" % i for i in range(1, n_cols)]
            for r in range(3)]
    md = _table_md(headers, rows)
    # Precondition: this is exactly the gap -- char-min fits, floor-min does not.
    fam = FAMILIES["helvetica"]
    char_w = text_width("0", fam.regular, BODY_SIZE)
    floor = 8 * char_w
    nat_sum, char_min_sum, budget = _natural_and_min(md)
    floor_min_sum = _floor_min_sum(md, floor)
    assert nat_sum > budget, "fixture should overflow at natural width"
    assert char_min_sum <= budget, "fixture should fit at one char per column (old gate shrank)"
    assert floor_min_sum > budget, "fixture should NOT fit at the readable floor (new gate panels)"

    blocks = render_document(parse(md), fam, content_width=LETTER_CONTENT_WIDTH)
    panels = _panels(blocks)
    assert len(panels) >= 2, f"expected panels, got {len(panels)}"
    # "Readable" threshold: well above a single glyph. The data cells here have
    # a natural width of ~6-7 chars (below the 8-char floor), so they render at
    # natural width, not crushed -- assert several characters wide, not one.
    one_char = text_width("0", fam.regular, BODY_SIZE)
    for p in panels:
        meta = p.prepositioned_table
        # Each panel fits the page.
        assert meta["table_width"] <= LETTER_CONTENT_WIDTH + 0.5
        # Columns are NOT crushed to one character: the widest data column in
        # each panel is several glyphs wide (the old gate crushed it to ~1).
        widest = _panel_widest_data_col_content(p)
        assert widest >= 4 * one_char, (
            f"panel columns crushed: widest data col {widest:.1f}pt "
            f"< 4 chars ({4 * one_char:.1f}pt)"
        )


def test_gate_is_controlled_by_panel_min_chars():
    # The floor governs the gate: a table near the boundary shrinks (1 block)
    # at a small floor but panels at a large floor -- one coherent lever for
    # both whether and how to panel. Use a column count where the char-min
    # fits but a large floor does not.
    n_cols = 18
    headers = ["key"] + [f"Metric{i}" for i in range(1, n_cols)]
    rows = [["K%d" % r] + ["value%02d" % i for i in range(1, n_cols)]
            for r in range(2)]
    md = _table_md(headers, rows)
    n_small_floor = _panel_count(md, table_panel_min_chars=1)
    n_large_floor = _panel_count(md, table_panel_min_chars=16)
    assert n_small_floor == 1, "at a 1-char floor the table should shrink to one strip"
    assert n_large_floor >= 2, "at a 16-char floor the table should panel"


def test_panel_min_chars_is_monotonic():
    # Smaller floor -> more columns per panel -> fewer panels; larger floor ->
    # wider columns -> more panels. Check the relationship is non-decreasing in
    # the knob across several values.
    md = _wide_cell_panel_table_md(n_cols=30, n_rows=2, cell_len=20)
    counts = [(k, _panel_count(md, table_panel_min_chars=k)) for k in (4, 8, 16)]
    vals = [c for _k, c in counts]
    assert vals[0] <= vals[1] <= vals[2], f"not monotonic: {counts}"
    # And the extremes genuinely differ (the knob has visible effect).
    assert vals[0] < vals[2], f"knob had no effect across 4..16: {counts}"


def test_panel_min_chars_flat_override():
    md = _wide_cell_panel_table_md(n_cols=30, n_rows=2, cell_len=20)
    # A small floor via the flat override packs denser than the default.
    n_small = _panel_count(md, table_panel_min_chars=4)
    n_default = _panel_count(md)
    assert n_small <= n_default


def test_panel_min_chars_config_and_flat_wins():
    md = _wide_cell_panel_table_md(n_cols=30, n_rows=2, cell_len=20)
    # Via LayoutConfig.
    cfg_small = LayoutConfig(table_panel_min_chars=4)
    cfg_large = LayoutConfig(table_panel_min_chars=16)
    n_cfg_small = len(
        _panels(render_document(
            parse(md), FAMILIES["helvetica"],
            content_width=LETTER_CONTENT_WIDTH, table_panel_min_chars=4,
        ))
    )
    # compile-level: config large, flat small -> flat wins (denser = fewer).
    pdf_flat_small = inkmd.compile(
        md, layout=cfg_large, table_panel_min_chars=4
    )
    pdf_cfg_small = inkmd.compile(md, layout=cfg_small)
    assert pdf_flat_small == pdf_cfg_small  # flat 4 won over config 16
    # And config large alone makes more panels than config small alone.
    assert inkmd.compile(md, layout=cfg_large) != inkmd.compile(md, layout=cfg_small)


def test_panel_min_chars_invalid_raises():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    for bad in (0, -1, 2.5, "8", None, True):
        with pytest.raises(ValueError):
            inkmd.compile(md, table_panel_min_chars=bad)


def test_panel_min_chars_invalid_in_config_raises():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    with pytest.raises(ValueError):
        inkmd.compile(md, layout=LayoutConfig(table_panel_min_chars=0))


def test_floor_packing_is_lossless():
    # No cell text is dropped under the denser packing: every header and body
    # cell's text appears somewhere across the panels (col 0 is repeated, the
    # rest appear once). Wide cells so the shrink path is exercised.
    n_cols, n_rows = 30, 3
    md = _wide_cell_panel_table_md(n_cols=n_cols, n_rows=n_rows, cell_len=20)
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    assert len(_panels(blocks)) >= 2
    joined = _placed_text_joined(blocks)
    # Every distinct column-0 label survives.
    for r in range(n_rows):
        assert f"K{r}" in joined, f"dropped col-0 label K{r}"
    # Every data-column header survives.
    for i in range(1, n_cols):
        assert f"h{i}" in joined, f"dropped header h{i}"
    # The torture token's characters survive: the 29 data cols x 3 rows x 20
    # chars all placed (col 0 is the non-torture label, so the count is exact).
    placed_a = _placed_char_count(blocks, "a")
    assert placed_a == (n_cols - 1) * n_rows * 20


def test_key_column_narrower_than_floor_keeps_natural_width():
    # Regression: a narrow key column (natural < floor) must NOT be crushed
    # proportionally alongside the wide data columns. _shrink_to_budget
    # distributes by natural width, so without a floored per-column minimum a
    # short col 0 got squeezed to ~1-2 chars while data columns kept the floor.
    # Each panel column's minimum is now min(natural, floor), so col 0 keeps
    # its full natural width.
    n_cols = 30
    md = _wide_cell_panel_table_md(n_cols=n_cols, n_rows=4, cell_len=20)
    fam = FAMILIES["helvetica"]
    # Natural width of col 0 = the wider of its header ("key", bold) and its
    # cells ("K0".."K3", regular). It is far narrower than the 8-char floor.
    key_natural = max(
        text_width("key", fam.bold, BODY_SIZE),
        text_width("K0", fam.regular, BODY_SIZE),
    )
    char_w = text_width("0", fam.regular, BODY_SIZE)
    floor = 8 * char_w  # default table_panel_min_chars
    assert key_natural < floor  # precondition: col 0 is narrower than the floor

    blocks = render_document(
        parse(md), fam, content_width=LETTER_CONTENT_WIDTH
    )
    panels = _panels(blocks)
    assert len(panels) >= 2
    for p in panels:
        col_x = p.prepositioned_table["col_x"]
        col0_content = (col_x[1] - col_x[0]) - 2 * TABLE_CELL_PADDING_X
        # col 0 renders at its natural width (a hair of slack tolerance), NOT
        # crushed below it.
        assert col0_content == pytest.approx(key_natural, abs=0.5), (
            f"key column crushed to {col0_content:.1f}pt; "
            f"natural is {key_natural:.1f}pt"
        )


def test_key_column_wider_than_floor_is_still_capped():
    # The other side of the floor: a pathologically WIDE key column (natural
    # far wider than the page) is NOT unrestricted. Its emit minimum is
    # min(natural, floor) = the floor, so it shrinks toward the floor (cells
    # wrap) and the panel still fits the page -- it does not get to keep its
    # huge natural width.
    fam = FAMILIES["helvetica"]
    n_cols = 12
    headers = ["K" * 60] + [f"Metric{i}" for i in range(1, n_cols)]
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * n_cols) + "|"
    body = "\n".join(
        "| " + " | ".join(["K" * 60] + ["a" * 20] * (n_cols - 1)) + " |"
        for _ in range(3)
    )
    md = head + "\n" + sep + "\n" + body + "\n"

    key_natural = text_width("K" * 60, fam.bold, BODY_SIZE)
    assert key_natural > LETTER_CONTENT_WIDTH  # precondition: wider than the page

    blocks = render_document(parse(md), fam, content_width=LETTER_CONTENT_WIDTH)
    panels = _panels(blocks)
    assert len(panels) >= 1
    for p in panels:
        meta = p.prepositioned_table
        # The panel fits the page (col 0 was capped, not left at its natural).
        assert meta["table_width"] <= LETTER_CONTENT_WIDTH + 0.5
        col_x = meta["col_x"]
        col0_content = (col_x[1] - col_x[0]) - 2 * TABLE_CELL_PADDING_X
        # Capped well below its 520pt natural (it cannot exceed the content
        # width, and in practice sits near the floor plus its slack share).
        assert col0_content < LETTER_CONTENT_WIDTH


# --- panels are the LAST RESORT (regression for the over-eager-panel bug) --
#
# A real-world table of a handful of short-token columns can overflow at its
# NATURAL (one-line) widths yet still fit when columns shrink and cells wrap
# to two lines. That is lossless and must be tried BEFORE panels. The gin-gonic
# benchmark README (5 columns of `ns/op` numbers) regressed into panels under
# the first cut; this pins that it renders as a single table instead.


def test_overflowing_but_shrinkable_table_does_not_panel():
    # 6 columns of short tokens: natural width overflows the page, but the
    # one-char-per-column minimum fits, so wrap mode shrink-wraps onto a single
    # strip -- it must NOT split into panels.
    headers = ["Benchmark", "Time", "Bytes", "Allocs", "Delta", "Notes"]
    rows = [
        ["BenchmarkOneRouteJSON", "25084 ns/op", "8192 B/op",
         "42 allocs/op", "+1.2%", "baseline"],
        ["BenchmarkRecursiveRoute", "31022 ns/op", "9011 B/op",
         "51 allocs/op", "-0.4%", "nested"],
        ["BenchmarkManyRouterGet", "18840 ns/op", "7040 B/op",
         "33 allocs/op", "+0.0%", "flat"],
    ]
    md = _table_md(headers, rows)
    # Prove the precondition: overflows at natural width, fits at min width.
    natural_sum, min_sum, budget = _natural_and_min(md)
    assert natural_sum > budget, "fixture must overflow at natural width"
    assert min_sum <= budget, "fixture must fit at one char per column"
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    # Exactly one table block: shrink-wrapped, not panelled.
    assert len(_panels(blocks)) == 1


def test_overflowing_but_shrinkable_wrap_bytes_match_shrink():
    # The shrink-wrap path in wrap mode is the SAME render shrink mode produces,
    # so the bytes are identical -- the strongest proof wrap did not panel.
    headers = ["Benchmark", "Time", "Bytes", "Allocs", "Delta", "Notes"]
    rows = [
        ["BenchmarkOneRouteJSON", "25084 ns/op", "8192 B/op",
         "42 allocs/op", "+1.2%", "baseline"],
        ["BenchmarkRecursiveRoute", "31022 ns/op", "9011 B/op",
         "51 allocs/op", "-0.4%", "nested"],
    ]
    md = _table_md(headers, rows)
    natural_sum, min_sum, budget = _natural_and_min(md)
    assert natural_sum > budget and min_sum <= budget
    assert inkmd.compile(md, table_overflow="wrap") == inkmd.compile(
        md, table_overflow="shrink"
    )


# --- byte-identity: a fitting table is the same in every mode --------------


def test_fitting_table_byte_identical_across_modes():
    md = (
        "# Doc\n\n"
        "| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n"
    )
    outs = {
        m: inkmd.compile(md, table_overflow=m)
        for m in ("wrap", "shrink", "warn", "error")
    }
    ref = outs["wrap"]
    for mode, out in outs.items():
        assert out == ref, f"fitting table differs in {mode!r} mode"


def test_default_mode_is_wrap_and_matches():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert inkmd.compile(md) == inkmd.compile(md, table_overflow="wrap")


# --- shrink / warn modes --------------------------------------------------


def test_shrink_mode_single_block_not_wrapped():
    md = _wide_table_md(n_cols=12, n_rows=2)
    blocks = render_document(
        parse(md),
        FAMILIES["helvetica"],
        content_width=LETTER_CONTENT_WIDTH,
        table_overflow="shrink",
    )
    # shrink never wraps: a single prepositioned table block.
    assert len(_panels(blocks)) == 1


def test_shrink_mode_overflows_right_as_before():
    # The shrunk table parks columns at their minima and overflows the budget
    # to the right (the pre-0.5 behaviour for a genuinely-too-wide table).
    md = _wide_table_md(n_cols=30, n_rows=2)
    blocks = render_document(
        parse(md),
        FAMILIES["helvetica"],
        content_width=LETTER_CONTENT_WIDTH,
        table_overflow="shrink",
    )
    panel = _panels(blocks)[0]
    assert panel.prepositioned_table["table_width"] > LETTER_CONTENT_WIDTH


def test_warn_mode_emits_one_warning():
    md = _wide_table_md(n_cols=12, n_rows=2)
    with pytest.warns(TableOverflowWarning):
        inkmd.compile(md, table_overflow="warn")


def test_warn_mode_bytes_match_shrink_mode():
    md = _wide_table_md(n_cols=12, n_rows=2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", TableOverflowWarning)
        warn_bytes = inkmd.compile(md, table_overflow="warn")
    shrink_bytes = inkmd.compile(md, table_overflow="shrink")
    assert warn_bytes == shrink_bytes


def test_fitting_table_warn_mode_emits_no_warning():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    with warnings.catch_warnings():
        warnings.simplefilter("error", TableOverflowWarning)
        # Should not raise: a fitting table never warns, even in warn mode.
        inkmd.compile(md, table_overflow="warn")


# --- error mode -----------------------------------------------------------


def test_error_mode_raises_on_wide_table():
    md = _wide_table_md(n_cols=12, n_rows=2)
    with pytest.raises(TableOverflowError):
        inkmd.compile(md, table_overflow="error")


def test_error_mode_does_not_raise_on_fitting_table():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    # No raise -> a valid PDF.
    assert inkmd.compile(md, table_overflow="error")[:4] == b"%PDF"


def test_error_message_names_the_table():
    md = _table_md(
        ["Identifier"] + [f"H{i}" for i in range(11)],
        [[f"datum{i}" for i in range(12)]],
    )
    with pytest.raises(TableOverflowError) as ei:
        inkmd.compile(md, table_overflow="error")
    assert "Identifier" in str(ei.value)


# --- long unbreakable tokens: char-wrapping always saves them -------------
#
# An "unbreakable monster column" does NOT exist at a normal font size: a
# column's minimum width is its WIDEST SINGLE CHARACTER (wrap_runs can always
# break any token to one char per line), so a 200-char token has a one-glyph
# minimum and shrink-wraps onto one strip. These tests pin that reality -- a
# long token shrink-wraps with NO warning and NO panels -- so a future change
# can't quietly resurrect the old over-eager warn/panel behaviour.


def test_long_token_two_col_shrink_wraps_no_warning():
    # A 200-char token's column shrinks to one char per line; the table fits
    # on one strip. No panels, no warning -- char-wrapping saves it.
    monster = "X" * 200
    md = f"| Key | Data |\n|---|---|\n| a | {monster} |\n"
    natural_sum, min_sum, budget = _natural_and_min(md)
    assert min_sum <= budget  # fits at one char per column -> shrink-wrap
    with warnings.catch_warnings():
        warnings.simplefilter("error", TableOverflowWarning)
        out = inkmd.compile(md)  # must NOT warn
    assert out[:4] == b"%PDF"


def test_long_token_does_not_wrap_into_panels():
    monster = "X" * 200
    md = f"| Key | Data |\n|---|---|\n| a | {monster} |\n"
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    # Shrink-wrap is a single block, not multiple panels.
    assert len(_panels(blocks)) == 1


def test_single_column_long_token_shrink_wraps_no_warning():
    # Even a single-column table whose only column holds a long token fits at
    # one char per line, so it shrink-wraps without warning (not tier 3).
    mono = "X" * 150
    md = f"| {mono} |\n|---|\n| {mono} |\n"
    natural_sum, min_sum, budget = _natural_and_min(md)
    assert min_sum <= budget
    with warnings.catch_warnings():
        warnings.simplefilter("error", TableOverflowWarning)
        out = inkmd.compile(md)
    assert out[:4] == b"%PDF"
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    assert len(_panels(blocks)) == 1


def test_single_column_long_token_does_not_hang():
    # A defensive timeout-free check: a very long single-column token renders
    # to a single block (no infinite loop in the column-fitting path).
    mono = "Z" * 300
    md = f"| {mono} |\n|---|\n| {mono} |\n"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", TableOverflowWarning)
        blocks = render_document(
            parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
        )
    assert len(_panels(blocks)) == 1


# --- tier 3: genuinely un-shrinkable (one glyph wider than the page) -------
#
# The tier-3 fallback (groups is None -> shrink + TableOverflowWarning) is
# reachable ONLY when a single glyph is physically wider than the text
# column, which at the base-14 fonts needs a pathological font size (a
# single char at ~400pt is wider than half a letter page). At normal sizes
# char-wrapping always saves the column, so this branch never fires for
# ordinary documents -- it is a defensive guard, exercised here at a giant
# font size to prove it is reachable and behaves (warn + render, no crash,
# no infinite loop) rather than dead. See the worker report for the
# reachability analysis.


def test_tier3_giant_font_two_columns_warns_and_renders():
    # Two columns whose single glyph is wider than the page cannot be paired
    # into even a 2-col panel -> _partition_columns returns None -> tier 3.
    md = "| W | M |\n|---|---|\n| W | M |\n"
    natural_sum, min_sum, budget = _natural_and_min(md)  # body-size sanity only
    with pytest.warns(TableOverflowWarning):
        out = inkmd.compile(md, font_size=400.0)
    assert out[:4] == b"%PDF"


def test_tier3_giant_font_single_column_warns_and_renders():
    md = "| W |\n|---|\n| W |\n"
    with pytest.warns(TableOverflowWarning):
        out = inkmd.compile(md, font_size=600.0)
    assert out[:4] == b"%PDF"


def test_partition_returns_none_when_floor_pair_overflows():
    # The guard is now reachable only when even a FLOORED [key, col] pair
    # overflows -- i.e. the floor itself (per column) is wider than half the
    # page. With a 300pt floor, two floored columns + padding = 624pt > 468pt,
    # so no pair fits and partition bails to tier 3. (At a normal ~54pt floor
    # the same columns would pair fine -- a wide column is no longer a monster
    # because it counts at the floor and is shrunk in the panel.)
    natural = [500.0, 500.0, 500.0]
    assert _partition_columns(
        natural, content_width=468.0, padding_x=6.0, floor_width=300.0
    ) is None
    # Sanity: at a normal floor the same columns DO pair (not None).
    assert _partition_columns(
        natural, content_width=468.0, padding_x=6.0, floor_width=54.0
    ) is not None


# --- knob plumbing --------------------------------------------------------


def test_flat_override_shrink():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert inkmd.compile(md, table_overflow="shrink")[:4] == b"%PDF"


def test_layout_config_field():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    cfg = LayoutConfig(table_overflow="error")
    # Fits, so error mode does not raise.
    assert inkmd.compile(md, layout=cfg)[:4] == b"%PDF"


def test_flat_override_wins_over_config():
    # config says error, flat says wrap -> wrap wins, so a WIDE table does not
    # raise (it wraps instead).
    md = _wide_table_md(n_cols=12, n_rows=1)
    cfg = LayoutConfig(table_overflow="error")
    out = inkmd.compile(md, layout=cfg, table_overflow="wrap")
    assert out[:4] == b"%PDF"


def test_flat_override_wins_config_wrap_flat_error():
    # The other direction: config wrap, flat error -> error wins, raises.
    md = _wide_table_md(n_cols=12, n_rows=1)
    cfg = LayoutConfig(table_overflow="wrap")
    with pytest.raises(TableOverflowError):
        inkmd.compile(md, layout=cfg, table_overflow="error")


def test_invalid_mode_raises_value_error():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    with pytest.raises(ValueError):
        inkmd.compile(md, table_overflow="nope")


def test_invalid_mode_in_config_raises_value_error():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    with pytest.raises(ValueError):
        inkmd.compile(md, layout=LayoutConfig(table_overflow="bogus"))


def test_classes_exported():
    assert inkmd.TableOverflowWarning is TableOverflowWarning
    assert inkmd.TableOverflowError is TableOverflowError
    assert "TableOverflowWarning" in inkmd.__all__
    assert "TableOverflowError" in inkmd.__all__


# --- pagination / landscape / page-break interaction ----------------------


def test_wide_and_tall_table_paginates_without_crash():
    # A wide table (wraps to panels) that is also tall (many rows) must cross
    # page boundaries and still produce a sane page count.
    md = _wide_table_md(n_cols=12, n_rows=60)
    pdf = inkmd.compile(md)
    assert pdf[:4] == b"%PDF"
    n = _pdf_page_count(pdf)
    assert n >= 2, f"a 12-col x 60-row wrapped table should span >= 2 pages, got {n}"


def test_landscape_needs_fewer_panels_than_portrait():
    # A 30-col un-fittable table panels in portrait (~3 panels). Landscape's
    # wider column either fits more columns per panel or shrink-wraps onto one
    # strip; either way it needs strictly fewer panels.
    md = _panel_forcing_table_md(n_cols=30, n_rows=2)
    portrait = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    landscape = render_document(
        parse(md),
        FAMILIES["helvetica"],
        content_width=LANDSCAPE_LETTER_CONTENT_WIDTH,
    )
    p_panels = len(_panels(portrait))
    l_panels = len(_panels(landscape))
    assert p_panels >= 3
    assert l_panels < p_panels


def test_landscape_compile_runs():
    md = _panel_forcing_table_md(n_cols=30, n_rows=2)
    assert inkmd.compile(md, orientation="landscape")[:4] == b"%PDF"


def test_page_break_before_wide_table_starts_fresh_page():
    # A CSS page-break div before a wide table still starts it on a new page;
    # the wrap is unaffected. Machine signal: more pages than without it,
    # and a clean render.
    wide = _wide_table_md(n_cols=12, n_rows=2)
    no_break = "Intro paragraph.\n\n" + wide
    with_break = (
        'Intro paragraph.\n\n'
        '<div style="page-break-after: always"></div>\n\n' + wide
    )
    pdf_no = inkmd.compile(no_break)
    pdf_yes = inkmd.compile(with_break)
    assert pdf_yes[:4] == b"%PDF"
    assert _pdf_page_count(pdf_yes) > _pdf_page_count(pdf_no)


# --- height floor: a shrunk column never strands cells in a page-tall row ---
#
# When a too-wide table is shrunk to fit, a narrow column with long content
# (e.g. a 50-char key) used to crush to ~1 char and wrap to ~49 lines, making
# every row taller than a page; the other cells were stranded on line 1 and
# the data read as a tower with the rest off the bottom. The height floor caps
# how narrow a column may be shrunk so its tallest cell, plus the header, still
# fit one page. Applies to shrink mode AND each panel's internal shrink.


def _max_row_block_height(block):
    """Header height + the tallest body-row height of a prepositioned table."""
    meta = block.prepositioned_table
    header_h = meta["header"]["height"]
    body_h = max((r["height"] for r in meta["rows"]), default=0.0)
    return header_h, body_h


def _widekey_shrink_md(n_cols=24, n_rows=3, key_len=50):
    headers = ["K" * key_len] + [f"Metric{i}" for i in range(1, n_cols)]
    rows = [["K" * key_len] + ["v%d_%d" % (r, i) for i in range(1, n_cols)]
            for r in range(n_rows)]
    return _table_md(headers, rows)


def test_height_floor_shrink_mode_row_fits_page():
    # The 50-char-key / 24-col table in shrink mode: header + one data row must
    # fit one usable page height (was ~726pt per row, far over 648pt).
    md = _widekey_shrink_md()
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH,
        table_overflow="shrink", usable_height=LETTER_USABLE_HEIGHT,
    )
    panels = _panels(blocks)
    assert len(panels) == 1  # shrink mode never panels
    header_h, body_h = _max_row_block_height(panels[0])
    assert header_h + body_h <= LETTER_USABLE_HEIGHT, (
        f"header + data row = {header_h + body_h:.0f}pt exceeds the usable "
        f"page height {LETTER_USABLE_HEIGHT}pt (tower not capped)"
    )


def test_height_floor_widens_the_key_column():
    # The floor makes the key column wider than one character, so its content
    # wraps to a page-fitting number of lines instead of one glyph per line.
    md = _widekey_shrink_md()
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH,
        table_overflow="shrink", usable_height=LETTER_USABLE_HEIGHT,
    )
    meta = _panels(blocks)[0].prepositioned_table
    col_x = meta["col_x"]
    key_content = (col_x[1] - col_x[0]) - 2 * TABLE_CELL_PADDING_X
    one_char = text_width("0", FAMILIES["helvetica"].regular, BODY_SIZE)
    # Comfortably more than a single glyph (the old crush was ~1 char).
    assert key_content >= 2.5 * one_char, (
        f"key column {key_content:.1f}pt is still near one char "
        f"({one_char:.1f}pt) -- height floor not applied"
    )


def test_height_floor_applies_in_panels():
    # A wrap-mode table whose one column holds a long cell must not let that
    # cell tower inside its panel: header + tallest row fits a page per panel.
    n_cols = 30
    headers = ["key"] + [f"h{i}" for i in range(1, n_cols)]
    rows = [["K%d" % r] + [("X" * 40 if i == 1 else "v%d" % i)
                           for i in range(1, n_cols)]
            for r in range(3)]
    md = _table_md(headers, rows)
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH,
        usable_height=LETTER_USABLE_HEIGHT,
    )
    panels = _panels(blocks)
    assert len(panels) >= 2
    for p in panels:
        header_h, body_h = _max_row_block_height(p)
        assert header_h + body_h <= LETTER_USABLE_HEIGHT, (
            f"a panel towers: header + row = {header_h + body_h:.0f}pt"
        )


def test_height_floor_irreducible_cell_paginates_lossless():
    # A single cell longer than a page at ANY width (5000 chars) caps at
    # content_width: the row genuinely exceeds a page and the existing row
    # pagination spills it across pages, losslessly, without crash or loop.
    giant = "Z" * 5000
    md = f"| key | data |\n|---|---|\n| row1 | {giant} |\n"
    pdf = inkmd.compile(md)  # must not hang/crash
    assert pdf[:4] == b"%PDF"
    assert _pdf_page_count(pdf) >= 2, "an over-a-page cell should span pages"
    pages = _paginate(md)
    z_placed = sum(
        r.text.count("Z")
        for pg in pages
        for ln in pg.lines
        if isinstance(ln, StyledLine)
        for r in ln.runs
    )
    assert z_placed == 5000, f"lossless: placed {z_placed}, expected 5000"


def test_height_floor_does_not_affect_short_celled_table():
    # A short-celled table that overflows at natural (so it shrinks) is
    # unchanged by the height floor: its cells wrap to one line well under the
    # budget, so the floor never binds. wrap == shrink bytes still holds.
    headers = ["Benchmark", "Time", "Bytes", "Allocs", "Delta", "Notes"]
    rows = [
        ["BenchmarkOneRouteJSON", "25084 ns/op", "8192 B/op",
         "42 allocs/op", "+1.2%", "baseline"],
        ["BenchmarkRecursiveRoute", "31022 ns/op", "9011 B/op",
         "51 allocs/op", "-0.4%", "nested"],
    ]
    md = _table_md(headers, rows)
    assert inkmd.compile(md, table_overflow="wrap") == inkmd.compile(
        md, table_overflow="shrink"
    )


def test_height_floor_fitting_table_byte_identical():
    # A table that fits at natural width never shrinks, so it never reaches the
    # height floor -- byte-identical across modes (fast path untouched).
    md = "# Doc\n\n| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n"
    outs = {m: inkmd.compile(md, table_overflow=m)
            for m in ("wrap", "shrink", "warn", "error")}
    assert len(set(outs.values())) == 1


# --- adversary / torture: inkmd never silently drops a cell ---------------
#
# Existence proof that the wide-table machinery (shrink-wrap, panels, and the
# tier-3 fallback) preserves every cell's content even at pathological scale.
# Each cell is a single no-space token, the maximally-unbreakable input
# (forces char-by-char wrapping). The robust invariant: column 0 holds a
# unique label per row that does NOT contain the torture character, and the
# torture string lives only in columns 1..n-1. Those columns are never
# repeated by the panel path, so the placed torture-char count is EXACT;
# meanwhile every distinct column-0 label must still appear (proving the
# key-column repetition is itself lossless). Both tests also assert the
# output is a structurally valid PDF (page-object count consistent with the
# page tree, xref + %%EOF present), not merely that it starts with %PDF.
#
# The cost of char-wrapping is super-linear in CELL LENGTH: a 1000-char cell
# shrunk to its one-character minimum wraps to ~1000 lines. Measured on
# letter: 60 cols x 1 row x 1000-char cells takes ~35s in render_document
# alone, and a single 1000-char cell shrunk to minimum is ~0.02s but dozens
# of them in one table interact super-linearly. So the literal worst case of
# 1000 columns x 1000 rows x 1000-char cells (one billion characters) is
# computationally infeasible -- it extrapolates to days of compute and
# gigabytes of output. The two tests below instead push each axis to a
# feasible extreme: Test A maxes CELL LENGTH (the literal 1000-char
# unbreakable cell), Test B maxes COLUMN COUNT (driving the panel path to
# ~100 panels). Together they prove the no-silent-drop invariant on every
# code path. Neither needs a slow marker; both run in a few seconds.


def test_torture_worst_case_unbreakable_cell_loses_nothing():
    # Test A: the literal 1000-character no-space cell. 8 columns x 6 rows,
    # so 7 torture columns x 6 rows x 1000 chars = 42000 characters that each
    # must survive char-by-char wrapping. Compiles in roughly 4s (this is the
    # slowest test in the file; the cost is the char-wrapping of the 1000-char
    # cells at minimum column width).
    n_cols, n_rows, cell_len = 8, 6, 1000
    md = _torture_table_md(n_cols, n_rows, cell_len)
    pdf = inkmd.compile(md)
    _assert_pdf_structurally_valid(pdf)
    # Every placed glyph is VISIBLE on its page, read from the real content
    # streams, and the exact count survives at the PDF level too. (The
    # blocks-layer count below cannot see placement; a glyph drawn below the
    # media box passed it. This closes that blind spot -- the S6f bug.)
    pages = _pdf_text_ops_by_page(pdf)
    _assert_text_ops_on_page(pages)
    _assert_rects_within_right_margin(_pdf_rects_by_page(pdf))
    assert sum(
        t.count("a") for ops in pages for _x, _y, t in ops
    ) == (n_cols - 1) * n_rows * cell_len
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    # Lossless: every torture character survives (torture columns 1..n-1 are
    # never repeated, so the count is exact).
    placed = _placed_char_count(blocks, "a")
    assert placed == (n_cols - 1) * n_rows * cell_len, (
        f"dropped torture content: placed {placed}, "
        f"expected {(n_cols - 1) * n_rows * cell_len}"
    )
    # Every distinct column-0 label survives (a shrunk col 0 may char-wrap the
    # label across lines, so check the concatenated placed text).
    joined = _placed_text_joined(blocks)
    for r in range(n_rows):
        assert f"K{r}" in joined, f"dropped column-0 label K{r}"


def test_torture_extreme_column_count_panels_lose_nothing():
    # Test B: extreme column count drives the panel path to ~100 panels (the
    # budget goes negative past ~39 columns, so column 0 repeats in every
    # panel). 200 columns x 100 rows of short no-space cells; 199 torture
    # columns x 100 rows x 20 chars = 398000 characters. Compiles in ~5s.
    n_cols, n_rows, cell_len = 200, 100, 20
    md = _torture_table_md(n_cols, n_rows, cell_len)
    pdf = inkmd.compile(md)
    _assert_pdf_structurally_valid(pdf)
    # Every placed glyph is VISIBLE on its page (real content streams), and
    # the exact torture count survives at the PDF level -- see Test A.
    pages = _pdf_text_ops_by_page(pdf)
    _assert_text_ops_on_page(pages)
    _assert_rects_within_right_margin(_pdf_rects_by_page(pdf))
    assert sum(
        t.count("a") for ops in pages for _x, _y, t in ops
    ) == (n_cols - 1) * n_rows * cell_len
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH
    )
    # Confirm we genuinely exercised the panel path at scale.
    assert len(_panels(blocks)) >= 2
    # Lossless: torture columns are never repeated, so the count is exact even
    # though column 0 is repeated across every panel.
    placed = _placed_char_count(blocks, "a")
    assert placed == (n_cols - 1) * n_rows * cell_len, (
        f"dropped torture content: placed {placed}, "
        f"expected {(n_cols - 1) * n_rows * cell_len}"
    )
    # Every one of the 100 distinct column-0 labels survives across all panels.
    joined = _placed_text_joined(blocks)
    for r in range(n_rows):
        assert f"K{r}" in joined, f"dropped column-0 label K{r}"


# --- S6f: page-tall groups are sliced across pages, nothing invisible -----
#
# The paginator places header and row groups atomically; before S6f a group
# taller than the page was drawn once and everything past the bottom edge
# landed OUTSIDE the media box -- present in the content stream (so the
# blocks-layer losslessness counts above all passed) but invisible to every
# PDF reader. These tests read the real content streams and assert the
# glyphs land where a reader can see them.


def test_giant_body_cell_slices_across_pages_all_glyphs_visible():
    # Repro 1: a single body cell taller than a page (5000 unbreakable Z
    # chars, ~85+ wrapped lines vs ~44 lines of usable letter height). The
    # cell must be sliced at line boundaries across pages, header repeating,
    # with every glyph on the visible page and reading order preserved.
    giant = "Z" * 5000
    md = f"| key | data |\n| --- | --- |\n| r1 | {giant} |\n| r2 | after |\n"
    pdf = inkmd.compile(md)
    _assert_pdf_structurally_valid(pdf)
    pages = _pdf_text_ops_by_page(pdf)
    _assert_text_ops_on_page(pages)
    _assert_rects_within_right_margin(_pdf_rects_by_page(pdf))
    # Lossless, counted from the real PDF bytes (not renderer internals).
    placed_z = sum(t.count("Z") for ops in pages for _x, _y, t in ops)
    assert placed_z == 5000, f"placed {placed_z} Z glyphs, expected 5000"
    # The cell genuinely spans multiple pages.
    z_pages = [
        i for i, ops in enumerate(pages) if any("Z" in t for _x, _y, t in ops)
    ]
    assert len(z_pages) >= 2, "an over-a-page cell should span pages"
    # Reading order: within each page the Z lines run strictly top to
    # bottom (strictly decreasing baselines, in emission order).
    for i in z_pages:
        z_ys = [y for _x, y, t in pages[i] if "Z" in t]
        assert all(a > b for a, b in zip(z_ys, z_ys[1:])), (
            f"page {i}: Z lines out of reading order"
        )
    # The header (which fits the page) keeps repeating at the top of each
    # page slice exactly as before, and nothing else was dropped.
    joined = _joined_pdf_text(pages)
    assert joined.count("key") == len(pages), (
        "the fitting header must repeat on every page slice"
    )
    assert "r1" in joined and "r2" in joined
    # The `r2 | after` row appears VISIBLY after the Z cell ends.
    after_pos = [
        (i, y)
        for i, ops in enumerate(pages)
        for _x, y, t in ops if "after" in t
    ]
    assert len(after_pos) == 1, "the 'after' cell must appear exactly once"
    ai, ay = after_pos[0]
    last_z_page = max(z_pages)
    last_z_y = min(y for _x, y, t in pages[last_z_page] if "Z" in t)
    assert ai > last_z_page or (ai == last_z_page and ay < last_z_y), (
        "the r2 row must come after the Z cell in reading order"
    )


def test_giant_header_renders_once_sliced_data_rows_visible():
    # Repro 2: a header cell taller than a page (3000 H chars, ~870pt vs
    # 648pt usable). Before S6f the truncated header re-drew at the top of
    # every page, so a data row never got a page with room: data-one and
    # data-two were never visible anywhere. Required: the header renders
    # ONCE, sliced across pages, then the data rows follow visibly. Later
    # pages having no column labels is intentional.
    big = "H" * 3000
    md = f"| key | {big} |\n| --- | --- |\n| r1 | data-one |\n| r2 | data-two |\n"
    pdf = inkmd.compile(md)
    _assert_pdf_structurally_valid(pdf)
    pages = _pdf_text_ops_by_page(pdf)
    _assert_text_ops_on_page(pages)
    _assert_rects_within_right_margin(_pdf_rects_by_page(pdf))
    # Header glyphs appear exactly once across the whole document: 3000
    # placed H chars total means no per-page repetition AND no truncation.
    placed_h = sum(t.count("H") for ops in pages for _x, _y, t in ops)
    assert placed_h == 3000, (
        f"placed {placed_h} H glyphs, expected exactly 3000 (header must "
        f"render once, sliced, not repeat per page)"
    )
    assert len(pages) >= 2, "a page-tall header should span pages"
    # Both data rows are VISIBLY on-page (the on-page sweep above already
    # proved every run visible; here: they exist, exactly once each).
    joined = _joined_pdf_text(pages)
    assert joined.count("data-one") == 1
    assert joined.count("data-two") == 1
    # And they read AFTER the header ends: the last H baseline precedes the
    # data rows in (page, top-to-bottom) order.
    h_pages = [
        i for i, ops in enumerate(pages) if any("H" in t for _x, _y, t in ops)
    ]
    last_h_page = max(h_pages)
    last_h_y = min(y for _x, y, t in pages[last_h_page] if "H" in t)
    for needle in ("data-one", "data-two"):
        di, dy = next(
            (i, y)
            for i, ops in enumerate(pages)
            for _x, y, t in ops if needle in t
        )
        assert di > last_h_page or (di == last_h_page and dy < last_h_y), (
            f"{needle} must come after the sliced header"
        )


def test_giant_key_header_in_panelled_table_lossless_on_page():
    # Panel interaction: a page-tall KEY-COLUMN header in a table wide
    # enough to panel. Each panel independently demotes its (repeated-key)
    # giant header to render-once-sliced; the header content therefore
    # appears once PER PANEL -- that verbosity is accepted and intentional.
    n_cols = 24
    headers = ["Q" * 3000] + [f"h{i}" for i in range(1, n_cols)]
    rows = [
        [f"K{r}"] + [f"r{r}v{i % 10}" for i in range(1, n_cols)]
        for r in range(2)
    ]
    md = _table_md(headers, rows)
    pdf = inkmd.compile(md)  # must compile
    _assert_pdf_structurally_valid(pdf)
    pages = _pdf_text_ops_by_page(pdf)
    _assert_text_ops_on_page(pages)
    _assert_rects_within_right_margin(_pdf_rects_by_page(pdf))
    joined = _joined_pdf_text(pages)
    # Panel count read from the PDF itself: one "(continued)" label per
    # continuation panel (drawn once per panel, never per page slice).
    n_panels = joined.count(TABLE_CONTINUED_LABEL) + 1
    assert n_panels >= 2, "fixture must actually panel"
    # Lossless: the giant key header appears exactly once per panel ...
    placed_q = sum(t.count("Q") for ops in pages for _x, _y, t in ops)
    assert placed_q == 3000 * n_panels, (
        f"placed {placed_q} Q glyphs, expected {3000 * n_panels} "
        f"(exactly once per panel across {n_panels} panels)"
    )
    # ... and every body cell and key label survives.
    for r in range(2):
        assert f"K{r}" in joined, f"dropped key label K{r}"
        for i in range(1, n_cols):
            assert f"r{r}v{i % 10}" in joined


# --- S6g: wrap mode contains tables within the content width (x-axis) -----
#
# The y-axis twin's counterpart: the height floor's irreducible branch used
# to return content_width as a column MINIMUM, so a panel adding other
# columns' floors on top blew past the budget and _shrink_to_budget returned
# minimums that overflowed the right margin -- grid rects and text runs past
# the media box, invisible. With S6f slicing page-tall cells safely, the
# floor is now best-effort in wrap mode: capped to the leftover after every
# other column takes its existing (token + readable-floor) minimum.


def test_cap_noop_returns_same_object_when_floors_fit():
    # The no-op property the frozen baseline rides on: minimums that fit the
    # budget come back as the IDENTICAL list object, so the shrinker input
    # (and output bytes) cannot change when nothing binds.
    base = [20.0, 30.0]
    floored = [20.0, 300.0]
    out = _cap_height_floored_mins(base, floored, 400.0)
    assert out is floored


def test_cap_noop_when_overflow_is_not_height_floored():
    # Overflow caused by base minimums alone (monster/giant-font territory)
    # is the documented pre-existing behaviour; the cap must not mask it.
    base = [300.0, 300.0]
    out = _cap_height_floored_mins(base, list(base), 400.0)
    assert out == base


def test_cap_single_floored_column_takes_exactly_the_leftover():
    # One height-floored column: it gets budget minus the other columns'
    # existing minimums, never below its own base, never above its floor.
    base = [25.0, 53.6]
    floored = [25.0, 468.0]
    out = _cap_height_floored_mins(base, floored, 444.0)
    assert out[0] == 25.0
    assert out[1] == pytest.approx(444.0 - 25.0)
    assert sum(out) == pytest.approx(444.0)


def test_cap_competing_floors_split_leftover_proportionally():
    # Two floored columns split the leftover proportionally to their
    # unconstrained floors (neither share reaches its floor here).
    base = [10.0, 10.0, 10.0]
    floored = [10.0, 100.0, 300.0]
    out = _cap_height_floored_mins(base, floored, 200.0)
    leftover = 200.0 - 30.0
    assert out[0] == 10.0
    assert out[1] == pytest.approx(10.0 + leftover * 100.0 / 400.0)
    assert out[2] == pytest.approx(10.0 + leftover * 300.0 / 400.0)
    assert sum(out) == pytest.approx(200.0)


def test_cap_waterfill_pins_a_small_floor_and_reflows_surplus():
    # A column whose proportional share exceeds its own floor is pinned AT
    # the floor; its surplus re-flows to the still-hungry column.
    base = [20.0, 20.0]
    floored = [25.0, 460.0]
    out = _cap_height_floored_mins(base, floored, 444.0)
    assert out[0] == 25.0  # pinned at its (small) floor
    assert out[1] == pytest.approx(444.0 - 25.0)  # the rest of the budget
    assert out[1] < 460.0  # still below its unconstrained floor


def test_cap_is_deterministic():
    base = [10.0, 10.0, 10.0, 10.0]
    floored = [10.0, 80.0, 250.0, 30.0]
    outs = {tuple(_cap_height_floored_mins(base, floored, 150.0))
            for _ in range(5)}
    assert len(outs) == 1


def test_irreducible_cell_column_capped_to_budget_in_wrap():
    # Integration: the giant-Z table's data column is height-floored all the
    # way to content_width (irreducible cell); in wrap mode it must take
    # exactly the leftover instead, and the emitted block must satisfy the
    # hard invariant table_width <= content_width.
    giant = "Z" * 5000
    md = f"| key | data |\n| --- | --- |\n| r1 | {giant} |\n| r2 | after |\n"
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH,
        usable_height=LETTER_USABLE_HEIGHT,
    )
    panels = _panels(blocks)
    assert len(panels) == 1
    meta = panels[0].prepositioned_table
    assert meta["table_width"] <= LETTER_CONTENT_WIDTH + 1e-6, (
        f"table {meta['table_width']:.1f}pt wide exceeds the "
        f"{LETTER_CONTENT_WIDTH}pt content column"
    )
    # The two columns consume the whole content budget: the key column at
    # its minimum, the Z column taking exactly the leftover.
    content_budget = LETTER_CONTENT_WIDTH - 2 * 2 * TABLE_CELL_PADDING_X
    col_x = meta["col_x"]
    key_w = (col_x[1] - col_x[0]) - 2 * TABLE_CELL_PADDING_X
    z_w = (meta["table_width"] - col_x[1]) - 2 * TABLE_CELL_PADDING_X
    assert key_w + z_w == pytest.approx(content_budget)
    assert z_w == pytest.approx(content_budget - key_w)
    assert z_w < LETTER_CONTENT_WIDTH  # no longer the full-content cap


def test_wrap_nothing_binds_is_byte_identical_to_shrink():
    # No-op guard at compile level: an overflowing-but-shrinkable table that
    # takes the wrap single-strip path with minimums that FIT the budget
    # must keep producing the EXACT shrink bytes (the capping logic must be
    # unobservable when nothing binds). Space-separated cell values keep
    # every token short, so neither the token minimums nor the height floor
    # push the minimum sum past the budget.
    headers = ["Endpoint", "Latency", "Throughput", "Errors", "CPU", "Notes"]
    rows = [
        ["GET /api/v1/users/profile", "12.4 ms p50", "8400 req/s",
         "0.02 %", "31 %", "cache warm"],
        ["POST /api/v1/orders/create", "48.9 ms p50", "1200 req/s",
         "0.40 %", "67 %", "writes to two shards"],
    ]
    md = _table_md(headers, rows)
    assert inkmd.compile(md, table_overflow="wrap") == inkmd.compile(
        md, table_overflow="shrink"
    )


def test_panel_giant_key_header_contained_within_margins():
    # The case the human reviewer failed: 24 columns, col-0 header of 3000
    # chars. Pre-S6g the panels drew ~880pt wide on a 612pt page (grid rects
    # to x=954, text starting at x=900, all invisible). Now every panel must
    # satisfy table_width <= its budget and nothing may pass the margin.
    n_cols = 24
    headers = ["Q" * 3000] + [f"h{i}" for i in range(1, n_cols)]
    rows = [
        [f"K{r}"] + [f"r{r}v{i % 10}" for i in range(1, n_cols)]
        for r in range(2)
    ]
    md = _table_md(headers, rows)
    blocks = render_document(
        parse(md), FAMILIES["helvetica"], content_width=LETTER_CONTENT_WIDTH,
        usable_height=LETTER_USABLE_HEIGHT,
    )
    for p in _panels(blocks):
        assert p.prepositioned_table["table_width"] <= (
            LETTER_CONTENT_WIDTH + 1e-6
        )
    pdf = inkmd.compile(md)
    _assert_rects_within_right_margin(_pdf_rects_by_page(pdf))
    pages = _pdf_text_ops_by_page(pdf)
    _assert_text_ops_on_page(pages)
