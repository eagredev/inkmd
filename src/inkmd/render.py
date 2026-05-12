"""Lower a parsed AST into the layout's run-based model.

The seam between markdown semantics (AST) and PDF layout (Run / paginate).
``render_document`` walks blocks, dispatches on type, and yields a list
of ``RenderedBlock`` records: a run list plus per-block spacing hints
that the paginator honours when stacking blocks on a page.

The font family is selectable so demo scripts can render samples in
Times (closer match to Nimbus on Linux for visual review) while the
library default stays Helvetica.
"""

from __future__ import annotations

from dataclasses import dataclass

from inkmd.ast import (
    AutoLink,
    BlockQuote,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    Heading,
    Inline,
    Link,
    List,
    ListItem,
    Paragraph,
    Strong,
    Table,
    TableCell,
    Text,
    ThematicBreak,
)
from inkmd.fonts import text_width
from inkmd.layout import Rect, Run, wrap_runs


@dataclass(frozen=True)
class FontFamily:
    """A coordinated set of fonts used together.

    regular: body text
    bold: **strong** emphasis
    italic: *emphasis*
    bold_italic: ***both***
    monospace: ``code``  (typically Courier regardless of family)
    """
    regular: str
    bold: str
    italic: str
    bold_italic: str
    monospace: str


HELVETICA_FAMILY = FontFamily(
    regular="Helvetica",
    bold="Helvetica-Bold",
    italic="Helvetica-Oblique",
    bold_italic="Helvetica-Bold",  # no Helvetica-BoldOblique in v0.1; bold standin
    monospace="Courier",
)


TIMES_FAMILY = FontFamily(
    regular="Times-Roman",
    bold="Times-Bold",
    italic="Times-Italic",
    bold_italic="Times-BoldItalic",
    monospace="Courier",
)


FAMILIES: dict[str, FontFamily] = {
    "helvetica": HELVETICA_FAMILY,
    "times": TIMES_FAMILY,
}


DEFAULT_FAMILY = HELVETICA_FAMILY
BODY_SIZE = 12.0


# Kept as module-level for compatibility with existing tests that import them.
BODY_FONT = DEFAULT_FAMILY.regular


# Heading size table (level 1..6). Values chosen for visual hierarchy at
# typical document scale; bold across the board.
HEADING_SIZES: dict[int, float] = {
    1: 24.0,
    2: 18.0,
    3: 14.0,
    4: 13.0,
    5: 12.0,
    6: 11.0,
}


@dataclass(frozen=True)
class RenderedBlock:
    """A paginatable unit: runs plus per-block vertical breathing room.

    ``space_above`` and ``space_below`` are in points and are *added* to
    the paginator's default inter-block spacing. Headings request more
    space above than below so they bind visually to their following body.

    For list items, ``body_indent`` is the left-margin offset (in points)
    that all body lines use; ``marker_runs`` is an optional sequence of
    runs to render at column 0 of the indented area's marker_x slot, on
    the first wrapped line only.
    """
    runs: tuple[Run, ...]
    space_above: float = 0.0
    space_below: float = 0.0
    body_indent: float = 0.0
    marker_runs: tuple[Run, ...] = ()
    marker_x: float = 0.0
    compact: bool = False  # if True, suppress inter-block paragraph_spacing before this block
    # Blockquote support: if set, draw a thin vertical bar at this x for
    # every line of this block.
    left_rule_x: float | None = None
    left_rule_fill: tuple[float, float, float] = (0.6, 0.6, 0.6)
    # Code block support: if set, draw a single background rectangle
    # spanning this block's full vertical extent (top of first line to
    # bottom of last line) with horizontal padding ``bg_padding``.
    background_fill: tuple[float, float, float] | None = None
    bg_padding: float = 4.0
    # Code blocks set this to suppress wrapping (lines are preserved as-is).
    preserve_lines: bool = False
    # Table support: when ``prepositioned`` is True, the block carries
    # already-positioned content. ``runs`` is empty; the paginator places
    # ``prepositioned_lines`` (one inner tuple per output line, in
    # top-down order) at the current y_cursor, advancing by ``line_heights``
    # per line, and drops ``prepositioned_shapes`` into the page shapes.
    # The layout treats the entire block as atomic for page-break purposes.
    prepositioned: bool = False
    prepositioned_lines: tuple = ()      # tuple of tuples of "PositionedRun"-like (relative y)
    prepositioned_line_heights: tuple = ()  # one float per line
    prepositioned_shapes: tuple = ()     # tuple of shape dicts with relative y


# Layout constants for lists. ``LIST_INDENT_PT`` is the horizontal step per
# nesting level — wide enough that the marker has room to sit visibly to
# the left of the body. The bullet marker is "•" (U+2022); WinAnsi maps it
# at byte 0x95.
LIST_INDENT_PT = 18.0
TIGHT_ITEM_SPACING = 0.0
LOOSE_ITEM_SPACING = 4.0
LIST_BLOCK_SPACE_ABOVE = 3.0
LIST_BLOCK_SPACE_BELOW = 3.0

# Blockquote layout.
QUOTE_INDENT_PT = 16.0          # how far the body is pushed past the rule
QUOTE_RULE_OFFSET_PT = 4.0      # x offset of the rule inside the indent
QUOTE_RULE_FILL = (0.7, 0.7, 0.7)

# Code block layout.
CODE_BG_FILL = (0.95, 0.95, 0.95)
CODE_PADDING_PT = 4.0
CODE_FONT_SIZE = 10.5

# Link styling.
LINK_COLOR = (0.0, 0.2, 0.8)  # blue, slightly desaturated for print-friendliness

# Table layout.
TABLE_CELL_PADDING_X = 6.0
TABLE_CELL_PADDING_Y = 3.0
TABLE_GRID_FILL = (0.5, 0.5, 0.5)
TABLE_GRID_WIDTH = 0.5
TABLE_HEADER_BG = (0.95, 0.95, 0.95)
TABLE_AVAILABLE_WIDTH = 468.0  # letter width minus default margins
TABLE_LINE_HEIGHT_RATIO = 1.2


def render_document(doc: Document, family: FontFamily = DEFAULT_FAMILY) -> list[RenderedBlock]:
    """Lower a Document into a list of ``RenderedBlock``."""
    blocks: list[RenderedBlock] = []
    for block in doc.blocks:
        blocks.extend(_render_block(block, family, depth=0))
    return blocks


def _render_block(block, family: FontFamily, depth: int) -> list[RenderedBlock]:
    """Lower one AST block (recursively for lists) to flat RenderedBlocks."""
    if isinstance(block, Heading):
        return [_render_heading(block, family)]
    if isinstance(block, Paragraph):
        return [RenderedBlock(runs=tuple(_render_paragraph(block, family)))]
    if isinstance(block, List):
        return _render_list(block, family, depth)
    if isinstance(block, BlockQuote):
        return _render_blockquote(block, family, depth)
    if isinstance(block, CodeBlock):
        return [_render_code_block(block, family)]
    if isinstance(block, Table):
        return [_render_table(block, family)]
    if isinstance(block, ThematicBreak):
        return [_render_thematic_break()]
    raise NotImplementedError(f"render: unsupported block {type(block).__name__}")


# Thematic break (---/***/___) — thin grey horizontal rule.
THEMATIC_BREAK_FILL = (0.7, 0.7, 0.7)
THEMATIC_BREAK_HEIGHT = 0.6


def _render_thematic_break() -> RenderedBlock:
    """A thin grey rectangle spanning the full body column.

    Uses the prepositioned path with a single shape and no positioned
    runs. The shape's x_offset is 0 and width spans the whole column;
    paginate_runs translates that to absolute coords. Total height
    includes a little vertical breathing room above and below the rule.
    """
    # Padding above and below so the rule doesn't crash into adjacent text.
    pad = 4.0
    return RenderedBlock(
        runs=(),
        space_above=pad,
        space_below=pad,
        prepositioned=True,
        prepositioned_lines=(),
        prepositioned_line_heights=(),
        prepositioned_shapes=(
            {
                "kind": "fill",
                "rel_y_top": 0.0,
                "height": THEMATIC_BREAK_HEIGHT,
                "x_offset": 0.0,
                "width": _COLUMN_WIDTH_FALLBACK,
                "fill": THEMATIC_BREAK_FILL,
            },
        ),
    )


# The thematic break shape needs to span the body column width, but the
# renderer doesn't know that here — pass a sentinel that the layout
# translates to (column_width - body_indent) at pagination time. We use
# letter's column width (8.5in - 2in margin = 6.5in = 468pt) as the
# default. The layout could be smarter about this but for now this is
# accurate for both A4 and letter at default margins.
_COLUMN_WIDTH_FALLBACK = 468.0


def _render_blockquote(quote: BlockQuote, family: FontFamily, depth: int) -> list[RenderedBlock]:
    """Flatten a BlockQuote: render inner blocks with extra indent and a left rule."""
    inner: list[RenderedBlock] = []
    for child in quote.blocks:
        inner.extend(_render_block(child, family, depth))
    out: list[RenderedBlock] = []
    for cb in inner:
        out.append(
            RenderedBlock(
                runs=cb.runs,
                space_above=cb.space_above,
                space_below=cb.space_below,
                body_indent=cb.body_indent + QUOTE_INDENT_PT,
                marker_runs=cb.marker_runs,
                marker_x=cb.marker_x + QUOTE_INDENT_PT,
                compact=cb.compact,
                left_rule_x=QUOTE_RULE_OFFSET_PT,
                left_rule_fill=QUOTE_RULE_FILL,
                background_fill=cb.background_fill,
                bg_padding=cb.bg_padding,
                preserve_lines=cb.preserve_lines,
            )
        )
    return out


def _render_table(table: Table, family: FontFamily) -> RenderedBlock:
    """Lower a Table to a pre-positioned RenderedBlock.

    Strategy: compute per-column widths from natural content widths,
    shrinking proportionally when needed; wrap each cell to its column;
    measure row heights; lay out positions (relative to table top-left,
    y=0 being the top); emit grid-line shapes and the header background.
    The layout layer translates everything to absolute page coordinates
    at pagination time.
    """
    n_cols = len(table.headers)
    if n_cols == 0:
        return RenderedBlock(runs=())

    # Lower every cell's inlines to a list of Runs. Headers are bold.
    def cell_runs(cell: TableCell, bold: bool) -> list[Run]:
        font = family.bold if bold else family.regular
        runs: list[Run] = []
        for inline in cell.inlines:
            runs.extend(_render_inline(inline, family, font=font))
        return runs

    header_runs = [cell_runs(c, bold=True) for c in table.headers]
    body_runs = [
        [cell_runs(c, bold=False) for c in row] for row in table.rows
    ]

    # 1. Natural column widths: max over header + body, of the unwrapped
    #    cell width (no padding, no border).
    def runs_natural_width(runs: list[Run]) -> float:
        return sum(text_width(r.text, r.font, r.size) for r in runs)

    natural = [0.0] * n_cols
    for i, runs in enumerate(header_runs):
        natural[i] = max(natural[i], runs_natural_width(runs))
    for row in body_runs:
        for i, runs in enumerate(row):
            natural[i] = max(natural[i], runs_natural_width(runs))

    # 2. Available content width per cell = column_width - 2 × padding.
    #    Total cell content width budget = available - n_cols × 2 padding.
    available_total = TABLE_AVAILABLE_WIDTH
    padding_total = n_cols * 2 * TABLE_CELL_PADDING_X
    content_budget = available_total - padding_total
    natural_sum = sum(natural)
    if natural_sum <= content_budget or natural_sum == 0:
        content_widths = list(natural)
        # Distribute remaining space proportionally — but keep natural
        # widths unless any cell needs more. Simplest: leave at natural.
    else:
        # Shrink proportionally to fit.
        scale = content_budget / natural_sum
        content_widths = [w * scale for w in natural]
    # Column widths include left + right padding.
    col_widths = [w + 2 * TABLE_CELL_PADDING_X for w in content_widths]
    # x positions: left edge of each column, relative to table left edge.
    col_x: list[float] = []
    x = 0.0
    for cw in col_widths:
        col_x.append(x)
        x += cw
    table_width = x

    # 3. Wrap every cell to its column's content width and measure row heights.
    def wrap_cell(runs: list[Run], col_idx: int) -> list[list[Run]]:
        if not runs:
            return [[]]
        return wrap_runs(runs, content_widths[col_idx]) or [[]]

    header_lines = [wrap_cell(header_runs[i], i) for i in range(n_cols)]
    body_lines = [
        [wrap_cell(row[i], i) for i in range(n_cols)] for row in body_runs
    ]

    line_height = BODY_SIZE * TABLE_LINE_HEIGHT_RATIO

    def row_height(cell_lines_per_col: list[list[list[Run]]]) -> float:
        max_lines = max((len(c) for c in cell_lines_per_col), default=1)
        return max_lines * line_height + 2 * TABLE_CELL_PADDING_Y

    header_h = row_height(header_lines)
    body_heights = [row_height(row) for row in body_lines]

    # 4. Compute y positions (relative to table top, y growing downward
    #    here; we'll flip when handed to the layout).
    row_tops = [0.0]  # header top
    row_tops.append(header_h)  # first body row top
    for h in body_heights[:-1]:
        row_tops.append(row_tops[-1] + h)
    total_height = header_h + sum(body_heights)

    # 5. Emit positioned content. We produce a flat list of "line records":
    #    each is (offset_y_baseline_from_top, tuple_of_PositionedRunLike).
    #    The layout reads these in order, advancing the page y_cursor by
    #    the y deltas implied by their baselines.
    PR = _PR  # local alias

    positioned_lines: list[tuple[float, tuple]] = []
    shapes: list[dict] = []

    # Header background tint.
    shapes.append({
        "kind": "fill",
        "rel_y_top": 0.0,
        "height": header_h,
        "x_offset": 0.0,
        "width": table_width,
        "fill": TABLE_HEADER_BG,
    })

    # Build positioned runs for one cell.
    def emit_cell(
        cell_lines: list[list[Run]],
        col_idx: int,
        row_top: float,
        alignment: str | None,
        is_header: bool,
    ) -> None:
        cw = col_widths[col_idx]
        x_left = col_x[col_idx] + TABLE_CELL_PADDING_X
        cell_content_w = content_widths[col_idx]
        # Baseline of first line: row_top + padding_y + ascent (~ line_height).
        # Use line_height as effective ascent for now (good enough at body size).
        baseline_y_from_top = row_top + TABLE_CELL_PADDING_Y + line_height
        for li, line in enumerate(cell_lines):
            # Compute aligned x offset for this line's content.
            line_w = sum(text_width(r.text, r.font, r.size) for r in line)
            if alignment == "center":
                x_start = x_left + (cell_content_w - line_w) / 2.0
            elif alignment == "right":
                x_start = x_left + (cell_content_w - line_w)
            else:
                x_start = x_left
            # Emit positioned runs for the line.
            runs_record: list[_PR] = []
            cx = x_start
            for run in line:
                runs_record.append(
                    PR(
                        text=run.text,
                        x_rel=cx,
                        y_from_top=baseline_y_from_top + li * line_height,
                        font=run.font,
                        size=run.size,
                        link_url=run.link_url,
                        color=run.color,
                    )
                )
                cx += text_width(run.text, run.font, run.size)
            if runs_record:
                positioned_lines.append((baseline_y_from_top + li * line_height, tuple(runs_record)))

    # Headers.
    for i in range(n_cols):
        emit_cell(header_lines[i], i, 0.0, table.alignments[i], is_header=True)

    # Body rows.
    for row_idx, row in enumerate(body_lines):
        row_top = row_tops[row_idx + 1]
        for i in range(n_cols):
            emit_cell(row[i], i, row_top, table.alignments[i], is_header=False)

    # 6. Grid lines as thin filled rectangles. Horizontal: top, below
    #    header, between body rows, bottom. Vertical: between columns + edges.
    h_lines_y: list[float] = []
    h_lines_y.append(0.0)
    h_lines_y.append(header_h)
    cumulative = header_h
    for h in body_heights:
        cumulative += h
        h_lines_y.append(cumulative)
    for y_top in h_lines_y:
        shapes.append({
            "kind": "fill",
            "rel_y_top": y_top - TABLE_GRID_WIDTH / 2.0,
            "height": TABLE_GRID_WIDTH,
            "x_offset": 0.0,
            "width": table_width,
            "fill": TABLE_GRID_FILL,
        })

    # Vertical grid lines: left edge of each column, plus right edge.
    v_lines_x = list(col_x) + [table_width]
    for vx in v_lines_x:
        shapes.append({
            "kind": "fill",
            "rel_y_top": 0.0,
            "height": total_height,
            "x_offset": vx - TABLE_GRID_WIDTH / 2.0,
            "width": TABLE_GRID_WIDTH,
            "fill": TABLE_GRID_FILL,
        })

    return RenderedBlock(
        runs=(),
        space_above=6.0,
        space_below=6.0,
        prepositioned=True,
        prepositioned_lines=tuple(positioned_lines),
        prepositioned_line_heights=(line_height,) * len(positioned_lines),
        prepositioned_shapes=tuple(shapes),
        # Stash total height in body_indent slot? No — use a custom attribute.
    )


# Lightweight namedtuple-ish for relative-positioned runs inside a table.
# We use a frozen dataclass so the renderer can stash these and the
# layout can read them as duck-typed records.
from dataclasses import dataclass as _dc

@_dc(frozen=True)
class _PR:
    text: str
    x_rel: float
    y_from_top: float
    font: str
    size: float
    link_url: str | None = None
    color: tuple[float, float, float] | None = None


def _render_code_block(cb: CodeBlock, family: FontFamily) -> RenderedBlock:
    """Lower a CodeBlock to a RenderedBlock with monospace + background fill."""
    # Each line becomes a run with embedded newline marker. The paginator
    # uses `preserve_lines=True` to split on '\n' rather than wrapping.
    runs = tuple(
        Run(text=cb.content, font=family.monospace, size=CODE_FONT_SIZE)
        for _ in [None]
    )
    return RenderedBlock(
        runs=runs,
        space_above=6.0,
        space_below=6.0,
        body_indent=CODE_PADDING_PT,
        background_fill=CODE_BG_FILL,
        bg_padding=CODE_PADDING_PT,
        preserve_lines=True,
    )


def _render_list(lst: List, family: FontFamily, depth: int) -> list[RenderedBlock]:
    """Flatten a List into a sequence of RenderedBlocks.

    Each item's first body-block carries the marker prefix and the
    item's body_indent. Subsequent body-blocks of the same item share
    the body_indent but have no marker. Nested lists recurse at deeper
    indent.
    """
    out: list[RenderedBlock] = []
    indent_for_items = LIST_INDENT_PT * (depth + 1)

    item_spacing = LOOSE_ITEM_SPACING if not lst.tight else TIGHT_ITEM_SPACING

    for item_idx, item in enumerate(lst.items):
        marker_text = _marker_text(lst, item_idx)
        marker_runs = (Run(text=marker_text, font=family.regular, size=BODY_SIZE),)
        marker_x = LIST_INDENT_PT * depth

        if not item.blocks:
            # An empty item still gets a marker-only line so it doesn't
            # vanish from the output. Source like `-\n- next\n-` produces
            # three items; the empty ones must remain visible to match
            # the author's intent.
            out.append(
                RenderedBlock(
                    runs=(),
                    space_above=0.0,
                    space_below=0.0,
                    body_indent=indent_for_items,
                    marker_runs=marker_runs,
                    marker_x=marker_x,
                    compact=lst.tight and item_idx > 0,
                )
            )
            continue

        first_of_item = True
        for sub_idx, child in enumerate(item.blocks):
            child_blocks = _render_block(child, family, depth + 1)
            for cb_idx, cb in enumerate(child_blocks):
                if first_of_item:
                    # Sibling items in a tight list pack flush together.
                    compact = lst.tight and item_idx > 0
                    rendered = RenderedBlock(
                        runs=cb.runs,
                        space_above=cb.space_above,
                        space_below=cb.space_below,
                        body_indent=indent_for_items,
                        marker_runs=marker_runs,
                        marker_x=marker_x,
                        compact=compact,
                    )
                    first_of_item = False
                else:
                    # Continuation block within the same item.
                    rendered = RenderedBlock(
                        runs=cb.runs,
                        space_above=cb.space_above,
                        space_below=cb.space_below,
                        body_indent=cb.body_indent or indent_for_items,
                        marker_runs=cb.marker_runs,
                        marker_x=cb.marker_x,
                        compact=cb.compact,
                    )
                out.append(rendered)

    return out


def _marker_text(lst: List, item_idx: int) -> str:
    """Format the marker string for the item at ``item_idx`` of ``lst``."""
    if lst.ordered:
        return f"{lst.start + item_idx}. "
    return "• "


def _render_paragraph(p: Paragraph, family: FontFamily) -> list[Run]:
    """Turn a Paragraph's inlines into a list of Runs."""
    runs: list[Run] = []
    for inline in p.inlines:
        runs.extend(_render_inline(inline, family, font=family.regular))
    return runs


def _render_heading(h: Heading, family: FontFamily) -> RenderedBlock:
    """Lower a Heading: bold face at the level-specific size, with spacing."""
    size = HEADING_SIZES[h.level]
    runs: list[Run] = []
    for inline in h.inlines:
        runs.extend(_render_inline(inline, family, font=family.bold, size=size))
    # H1 gets the most breathing room; subordinate levels get progressively less.
    space_above = max(size * 0.6, 6.0)
    space_below = max(size * 0.25, 3.0)
    return RenderedBlock(runs=tuple(runs), space_above=space_above, space_below=space_below)


def _render_inline(
    inline: Inline,
    family: FontFamily,
    font: str,
    size: float = BODY_SIZE,
    link_url: str | None = None,
) -> list[Run]:
    """Lower one inline node to one or more runs.

    ``font`` is the *current* font (carried through nesting) so that an
    Emphasis inside a Strong picks the family's ``bold_italic`` face
    instead of dropping back to plain italic. ``size`` and ``link_url``
    are carried through nesting — heading inlines stay at heading size,
    and a Strong inside a Link inherits the link annotation.
    """
    color = LINK_COLOR if link_url is not None else None

    if isinstance(inline, Text):
        return [Run(text=inline.content, font=font, size=size, link_url=link_url, color=color)]

    if isinstance(inline, Code):
        return [Run(
            text=inline.content, font=family.monospace, size=size,
            link_url=link_url, color=color,
        )]

    if isinstance(inline, Strong):
        next_font = (
            family.bold_italic if font == family.italic else family.bold
        )
        return _flatten(inline.inlines, family, next_font, size, link_url=link_url)

    if isinstance(inline, Emphasis):
        next_font = (
            family.bold_italic if font == family.bold else family.italic
        )
        return _flatten(inline.inlines, family, next_font, size, link_url=link_url)

    if isinstance(inline, Link):
        # Link children render at the same font/size but with link_url
        # propagated. CommonMark forbids nested links so we don't worry
        # about Link-inside-Link.
        return _flatten(inline.inlines, family, font, size, link_url=inline.url)

    if isinstance(inline, AutoLink):
        # AutoLink: URL is the destination; display text is the URL with
        # the mailto: prefix stripped if present (so an email autolink
        # shows the bare address, not "mailto:dylan@example.com").
        display = inline.url
        if display.startswith("mailto:"):
            display = display[len("mailto:"):]
        return [Run(
            text=display, font=font, size=size,
            link_url=inline.url, color=LINK_COLOR,
        )]

    raise NotImplementedError(f"render: unsupported inline {type(inline).__name__}")


def _flatten(
    inlines: tuple[Inline, ...],
    family: FontFamily,
    font: str,
    size: float = BODY_SIZE,
    link_url: str | None = None,
) -> list[Run]:
    """Render a tuple of inline children, carrying font + size + link_url."""
    runs: list[Run] = []
    for inline in inlines:
        runs.extend(_render_inline(inline, family, font=font, size=size, link_url=link_url))
    return runs
