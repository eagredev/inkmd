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

import re
import warnings
from dataclasses import dataclass, replace

from inkmd.ast import (
    AutoLink,
    BlockQuote,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    HardBreak,
    Heading,
    HtmlBlock,
    HtmlInline,
    Image,
    Inline,
    Kbd,
    Link,
    List,
    ListItem,
    Mark,
    PageBreak,
    Paragraph,
    Strikethrough,
    Strong,
    Subscript,
    Superscript,
    Table,
    TableCell,
    Text,
    ThematicBreak,
    Underline,
)
from inkmd.emoji import split_text_into_runs
from inkmd.fonts import text_width
from inkmd.layout import EMOJI_BASELINE_DROP, Rect, Run, emoji_box, wrap_runs


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
    bold_italic="Helvetica-BoldOblique",
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


# Heading size table (level 1..6) at the default body size (BODY_SIZE).
# Values chosen for visual hierarchy at typical document scale; bold across
# the board. These are NOT a clean multiple of body: H1 is 2.0x body, H2
# 1.5x, H3 14/12, H4 13/12, H5 1.0x, H6 11/12.
#
# Headings scale with the effective body size: _heading_size(level, body)
# returns body / BODY_SIZE * HEADING_SIZES[level]. At body == BODY_SIZE the
# factor is exactly 1.0, so every level reproduces its value here bit for bit
# (byte-identical default); at body == 24 each heading is exactly doubled.
HEADING_SIZES: dict[int, float] = {
    1: 24.0,
    2: 18.0,
    3: 14.0,
    4: 13.0,
    5: 12.0,
    6: 11.0,
}


def _heading_size(level: int, body_size: float) -> float:
    """Heading point size for ``level`` at the given effective ``body_size``.

    Scales the default-size heading (HEADING_SIZES[level]) by the body ratio
    body_size / BODY_SIZE. At body_size == BODY_SIZE the ratio is exactly 1.0,
    so the result is the original float unchanged.
    """
    return body_size / BODY_SIZE * HEADING_SIZES[level]


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
    # Forced page break: when True the block carries no content and the
    # paginator starts the next block on a fresh page (from a CSS page-break
    # div). Default False so every other construction is unaffected.
    page_break: bool = False
    # Blockquote support: each entry is an x offset (relative to the
    # left margin) where a thin vertical rule should be drawn for every
    # line of this block. Nested blockquotes accumulate rules so each
    # depth gets its own visible bar — the outermost at the leftmost x,
    # inner rules at progressively deeper x positions.
    left_rules: tuple[float, ...] = ()
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
    # Set for tables: a dict of row groups (header + per-row, row-local
    # coords) the layout can split across pages, repeating the header. The
    # flat prepositioned_* fields above are the single-page/atomic view of
    # the same content; the layout prefers prepositioned_table when present.
    prepositioned_table: dict | None = None


# Layout constants for lists. ``LIST_INDENT_PT`` is the horizontal step per
# nesting level — wide enough that the marker has room to sit visibly to
# the left of the body. The bullet marker is "•" (U+2022); WinAnsi maps it
# at byte 0x95.
LIST_INDENT_PT = 18.0
# Minimum gap between an ordered-list marker and the body text when the
# marker is wide enough (multi-digit) to need a slot wider than one
# indent step.
MARKER_BODY_GAP = 4.0
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
# Fenced-code font size at the default body size. Fenced code scales with the
# effective body size via the ratio CODE_FONT_SIZE / BODY_SIZE (0.875), so it
# stays slightly smaller than body at every size; at body == BODY_SIZE the
# rendered size is exactly this value. Inline code uses the body size directly.
CODE_FONT_SIZE = 10.5

# Link styling.
LINK_COLOR = (0.0, 0.2, 0.8)  # blue, slightly desaturated for print-friendliness

# Table layout.
TABLE_CELL_PADDING_X = 6.0
TABLE_CELL_PADDING_Y = 3.0
TABLE_GRID_FILL = (0.5, 0.5, 0.5)
TABLE_GRID_WIDTH = 0.5
TABLE_HEADER_BG = (0.95, 0.95, 0.95)
# Default text-column width: letter (8.5in) minus two 1in margins = 468pt.
# A4 documents pass their own narrower width (595 - 144 = 451pt) through
# render_document so tables and images stay inside the page margins.
DEFAULT_CONTENT_WIDTH = 468.0
# Default usable vertical space: letter (11in) minus two 1in margins = 648pt.
# compile() passes the height derived from the actual page size + margin; this
# default keeps other callers/tests (which work in width-space) unaffected.
DEFAULT_USABLE_HEIGHT = 648.0
# Retained as an alias for the default; the live budget is now passed in.
TABLE_AVAILABLE_WIDTH = DEFAULT_CONTENT_WIDTH
TABLE_LINE_HEIGHT_RATIO = 1.2
# Minimum content width per column so the proportional-shrink path
# can't squeeze short columns to near-zero, jamming text against
# borders. ~3em at body size (12pt × ~1.75).
TABLE_MIN_CONTENT_WIDTH = 21.0

# Vertical gap between stacked panels in table_overflow="wrap" (about one
# blank body line at the default size). Applied as the space below each
# panel except the last, on top of the paginator's default inter-block gap.
TABLE_PANEL_GAP = 12.0

# Marker text placed on its own faint line above every continuation panel
# (panels 2..N) in wrap mode, so a reader knows the panel continues the same
# table's columns rather than starting a new one. ASCII only.
TABLE_CONTINUED_LABEL = "(continued)"

# Default per-data-column floor, in character widths, for packing panels in
# wrap mode (mirrors LayoutConfig.table_panel_min_chars). When deciding how
# many columns fit a panel, each column is allowed to shrink to at most this
# many character widths; the panel is then emitted via shrink-to-budget so its
# cells wrap. Larger -> wider columns, more panels; smaller -> denser packing.
TABLE_PANEL_MIN_CHARS = 8


class TableOverflowWarning(UserWarning):
    """A wide table could not be fit losslessly and was shrunk (S6).

    Emitted once per offending table in ``table_overflow="warn"`` mode
    (the explicit "tell me when a table overflows" mode), and also in the
    default ``"wrap"`` mode when a table has a single column wider than the
    text column -- an unbreakable monster cell that panel-wrapping cannot
    split, so inkmd falls back to shrinking it and letting it overflow the
    right edge. The message names the table by document order and first
    header cell so the author can find it. Subclasses :class:`UserWarning`
    so it shows by default but stays filterable
    (``warnings.simplefilter("ignore", TableOverflowWarning)``).
    """


class TableOverflowError(Exception):
    """A table is too wide to fit the text column (S6).

    Raised only in ``table_overflow="error"`` mode, the CI-gate mode for
    authors who must guarantee no table ever overflows. The message names
    the table by document order and first header cell. Other modes never
    raise this: ``"wrap"`` fits the table losslessly (or shrinks an
    unbreakable single column with a :class:`TableOverflowWarning`),
    ``"shrink"`` shrinks silently, and ``"warn"`` shrinks with a warning.
    """


def _widest_token_width(
    header_runs: list[Run],
    body_runs: list[list[list[Run]]],
    col_idx: int,
) -> float:
    """Width of the widest single *character* in column ``col_idx``.

    This is the column's true lower-bound content width: ``wrap_runs``
    can always break a long token down to one character per line (see
    ``layout._break_long_token``'s character-level fallback), so any
    column at least one glyph wide can render its content without a
    glyph escaping the cell. Using the widest whole token instead would
    overstate the minimum for cells holding a single very long
    unbreakable run (a 300-char identifier, a row of W's), forcing the
    whole table to overflow when char-level wrapping would have fit it.

    Header counts as one of the rows. Returns at least 1.0 to avoid
    zero-width columns when a column is fully empty.
    """
    widest = 1.0
    def measure(runs: list[Run]) -> float:
        # Measure each non-whitespace character; the widest one is the
        # narrowest the column can be while still wrapping char-by-char.
        col_widest = 0.0
        for r in runs:
            for ch in r.text:
                if ch.isspace():
                    continue
                w = text_width(ch, r.font, r.size)
                if w > col_widest:
                    col_widest = w
        return col_widest
    widest = max(widest, measure(header_runs))
    for row in body_runs:
        widest = max(widest, measure(row[col_idx]))
    return widest


def _shrink_to_budget(
    natural: list[float], budget: float, min_widths: list[float]
) -> list[float]:
    """Distribute ``budget`` across columns proportionally, enforcing
    per-column ``min_widths`` (typically widest-token-width per column).

    Algorithm:
      1. Compute the proportional share for each column.
      2. Clamp any below its min to the min.
      3. Recompute the remaining budget for unclamped columns and
         redistribute proportionally. Iterate until stable.
      4. If even the minima alone exceed the budget, keep each column at
         its minimum (so no column is crushed below the width of its
         widest unbreakable token). The table overflows the budget to the
         right, but content stays legible rather than collapsing onto the
         grid lines. The narrowest a minimum can be is one character, so
         columns never reach zero or negative width.
    """
    n = len(natural)
    if n == 0:
        return []
    # Guard the degenerate budget cases. A budget that is zero or negative
    # (e.g. so many columns that padding alone exceeds the page width)
    # would otherwise produce zero or negative column widths and fling
    # every cell onto the grid lines. Honour the minima instead.
    if budget <= 0 or sum(min_widths) > budget:
        return [max(m, 1.0) for m in min_widths]

    natural_sum = sum(natural) or 1.0
    widths = [w * budget / natural_sum for w in natural]
    for _ in range(n + 1):
        clamped_idx = [i for i, w in enumerate(widths) if w < min_widths[i]]
        if not clamped_idx:
            break
        free = [i for i in range(n) if i not in set(clamped_idx)]
        if not free:
            # Every column is clamped — done.
            for i in clamped_idx:
                widths[i] = min_widths[i]
            break
        clamped_total = sum(min_widths[i] for i in clamped_idx)
        remaining = budget - clamped_total
        free_natural_sum = sum(natural[i] for i in free) or 1.0
        new_widths = list(widths)
        for i in clamped_idx:
            new_widths[i] = min_widths[i]
        for i in free:
            new_widths[i] = natural[i] * remaining / free_natural_sum
        if new_widths == widths:
            break
        widths = new_widths
    return widths


def _cap_height_floored_mins(
    base_mins: list[float], floored_mins: list[float], budget: float,
) -> list[float]:
    """Make height floors BEST-EFFORT under a hard width budget (wrap only).

    ``floored_mins`` are the shrinker minimums after the height floor raised
    some columns (possibly all the way to content_width for an irreducible
    page-tall cell); ``base_mins`` are the same columns' minimums WITHOUT the
    height floor (widest-token min and, where the caller works at the
    readable floor, the readable-floor min). Both lists are elementwise
    ``floored_mins[i] >= base_mins[i]``.

    table_overflow="wrap" promises losslessness, and a min sum past the
    budget makes ``_shrink_to_budget`` return the minimums verbatim: the
    table overflows the right margin and glyphs land OUTSIDE the media box,
    invisible (the x-axis twin of the S6f bug). The height floor's
    irreducible cap-at-content_width premise ("a too-tall cell means buried
    content") is obsolete now that S6f slices page-tall groups across pages,
    so when the floors do not fit, the floor loses and the width budget
    wins: every column keeps its base minimum, and the height-floored
    columns split the LEFTOVER (budget minus the sum of base minimums)
    proportionally to their unconstrained floors, waterfilled so no column
    exceeds the floor it asked for (its surplus re-flows to the others) and
    none drops below its own base minimum. A capped column wraps to more
    lines, gets taller, and the S6f slicing carries it across pages: still
    lossless, now visible.

    No-op property (load-bearing for the frozen baseline): when
    ``floored_mins`` already fit the budget, the SAME list object is
    returned, so callers feed ``_shrink_to_budget`` bit-identical input and
    output bytes cannot change. Equally a no-op when nothing was height
    floored (the overflow then comes from base minimums: the pre-existing,
    documented monster/giant-font overflow, which this helper must not
    mask). Modes other than wrap never call this.

    Pure + deterministic: index-order iteration, no sets/clocks.
    """
    if sum(floored_mins) <= budget:
        return floored_mins
    n = len(floored_mins)
    bound = [i for i in range(n) if floored_mins[i] > base_mins[i]]
    if not bound:
        return floored_mins
    capped = list(base_mins)
    leftover = budget - sum(base_mins)
    # Waterfill: give each still-active floored column a share of the
    # leftover proportional to its unconstrained floor; a column whose share
    # would exceed that floor is pinned AT the floor and drops out, its
    # surplus re-flowing to the rest. Each pass pins at least one column or
    # finishes, so this terminates in <= len(bound) passes. Not all columns
    # can pin (that would mean the floors fit the budget, handled above).
    active = list(bound)
    while leftover > 0 and active:
        weight_sum = sum(floored_mins[i] for i in active)
        pinned = [
            i for i in active
            if base_mins[i] + leftover * (floored_mins[i] / weight_sum)
            >= floored_mins[i]
        ]
        if not pinned:
            for i in active:
                capped[i] = (
                    base_mins[i] + leftover * (floored_mins[i] / weight_sum)
                )
            break
        for i in pinned:
            capped[i] = floored_mins[i]
            leftover -= floored_mins[i] - base_mins[i]
        active = [i for i in active if i not in pinned]
    return capped


def _partition_columns(
    natural: list[float], content_width: float, padding_x: float,
    floor_width: float,
) -> list[list[int]] | None:
    """Greedily pack columns into page-width panels for table_overflow="wrap".

    Panels are the last resort, so a panel packs as DENSELY as it readably
    can: each column's packing width is ``min(natural[c], floor_width)`` --
    a column wider than the readable floor is counted at the floor (it will
    be shrunk + cell-wrapped when the panel is emitted), so many more columns
    fit per panel than packing at natural width would allow. ``floor_width``
    is ``table_panel_min_chars`` worth of an average glyph (see the caller).

    ``natural`` is each column's natural content width (no padding).
    ``content_width`` is the full text-column width a panel may occupy;
    ``padding_x`` is the per-side cell padding. A panel of columns ``g`` fits
    when ``sum(min(natural[c], floor_width) for c in g) + len(g)*2*padding_x
    <= content_width``.

    Column 0 is the KEY column: it leads group 1 naturally and is PREPENDED
    to every later group as a repeated label. The key column is floored by
    the same rule, so a pathologically wide key cannot by itself blow a panel.
    Returns a list of column-index groups in document order (col 0 first in
    each).

    Returns ``None`` (tier 3, "panels can't help") when:
    - the table has a single column that overflows (no data column to pair
      with col 0), or
    - column 0 plus any one data column still will not fit one panel even at
      the floor (only reachable at a pathological page size or font size,
      where a single floored glyph-width column exceeds the page).
    The caller falls back to shrink + a warning in that case.

    Pure + deterministic: iterates columns in index order, no sets/clocks.
    """
    n = len(natural)
    if n <= 1:
        # A 1-column (or 0-column) table has no data column to group with the
        # key column; if it overflowed to reach here, panels can't help.
        return None

    def packed(c: int) -> float:
        # A column counts at its readable floor, never wider: a too-wide
        # column will be shrunk + cell-wrapped inside the panel.
        return min(natural[c], floor_width)

    def panel_width(col_indices: list[int]) -> float:
        return (sum(packed(c) for c in col_indices)
                + len(col_indices) * 2 * padding_x)

    key = 0
    groups: list[list[int]] = []
    current = [key]
    for c in range(1, n):
        candidate = current + [c]
        if panel_width(candidate) <= content_width:
            current = candidate
            continue
        # ``c`` does not fit in the current group. Close the current group if
        # it already holds a data column; otherwise (current is just [key]) a
        # single col 0 + c won't fit even at the floor -- bail to tier 3.
        if len(current) == 1:
            return None
        groups.append(current)
        # Start a fresh group with the key column + this column. If even that
        # floored pair overflows, panels can't place this column at all.
        if panel_width([key, c]) > content_width:
            return None
        current = [key, c]
    groups.append(current)
    return groups


def render_document(
    doc: Document,
    family: FontFamily = DEFAULT_FAMILY,
    content_width: float = DEFAULT_CONTENT_WIDTH,
    *,
    body_size: float = BODY_SIZE,
    line_spacing: float = TABLE_LINE_HEIGHT_RATIO,
    table_overflow: str = "wrap",
    table_panel_min_chars: int = TABLE_PANEL_MIN_CHARS,
    usable_height: float = DEFAULT_USABLE_HEIGHT,
) -> list[RenderedBlock]:
    """Lower a Document into a list of ``RenderedBlock``.

    ``content_width`` is the available text-column width in points (page
    width minus both margins). Tables and block-level images are sized
    to it so they stay within the page margins. Defaults to the letter
    content width; ``compile`` passes the width derived from the actual
    page size so A4 documents do not overflow.

    ``body_size`` is the effective body font size in points. Body text,
    list markers, table cells, and captions render at this size; headings
    scale off it via _heading_size. Defaults to BODY_SIZE so other callers
    and tests are unaffected; ``compile`` passes the resolved
    ``effective.font_size``.

    ``line_spacing`` is the leading multiplier for table rows (row line
    height = body_size * line_spacing), so tables breathe with the same
    knob as prose. Defaults to TABLE_LINE_HEIGHT_RATIO so other callers
    and tests are unaffected; ``compile`` passes the resolved
    ``effective.line_spacing``. Only ``_render_table`` consumes it; the
    other helpers pass it through.

    ``table_overflow`` controls what happens to a table too wide for
    ``content_width``: ``"wrap"`` (default) stacks the columns into panels,
    ``"shrink"`` overflows the right edge silently, ``"warn"`` shrinks with
    a :class:`TableOverflowWarning`, and ``"error"`` raises
    :class:`TableOverflowError`. A table that FITS renders identically in
    every mode, so the default does not disturb existing output. Only
    ``_render_table`` consumes it; the other helpers pass it through.

    ``table_panel_min_chars`` is the per-data-column floor (in character
    widths) used when ``table_overflow="wrap"`` packs a too-wide table into
    panels: each column may shrink to at most this many characters before a
    new panel opens, so smaller values pack more columns per panel. Only the
    wrap panel-packing reads it; a fitting table and the other modes are
    unaffected. Defaults to TABLE_PANEL_MIN_CHARS so other callers and tests
    are unaffected; ``compile`` passes the resolved value.

    ``usable_height`` is the page's usable vertical space in points (page
    height minus both margins). A shrunk table uses it as a HEIGHT FLOOR on
    each column's minimum width: a column is never squeezed so narrow that its
    tallest cell wraps to more lines than one (header + data) row can hold on a
    page. Defaults to DEFAULT_USABLE_HEIGHT (letter) so other callers and tests
    are unaffected; ``compile`` passes the height from the actual page size.
    Only ``_render_table`` consumes it; the other helpers pass it through.
    """
    blocks: list[RenderedBlock] = []
    for block in doc.blocks:
        blocks.extend(_render_block(
            block, family, depth=0, content_width=content_width,
            body_size=body_size, line_spacing=line_spacing,
            table_overflow=table_overflow,
            table_panel_min_chars=table_panel_min_chars,
            usable_height=usable_height,
        ))
    return blocks


def apply_embedding(
    blocks: list[RenderedBlock], embedded_ref, missing: list | None = None
) -> list[RenderedBlock]:
    """Post-pass: split each block's runs at the WinAnsi boundary.

    Non-WinAnsi spans (Cyrillic / Greek / Latin-Ext) the embedded font can
    draw gain ``embedded_ref`` so they measure + emit via that font;
    base-14 spans are untouched; codepoints with no glyph at all become the
    visible ``[U+XXXX]`` marker on the base-14 lane (S6). Mirrors the emoji
    split, but runs AFTER the whole document is rendered, so
    ``_render_inline`` stays a pure base-14 producer.

    ``embedded_ref`` may be ``None`` (font-less build / no embedded font):
    then every non-base-14 codepoint is unrenderable and becomes a marker
    instead of a silent ``?``. ``missing`` (optional list) collects every
    unrenderable codepoint occurrence so the caller can raise one warning.

    Splits ``runs`` and ``marker_runs`` (list markers are base-14, so a
    split there is almost always a no-op, but routing them keeps a custom
    embedded marker correct). Prepositioned table content is NOT split here
    — table column widths are computed pre-split, so embedding/marking a
    table cell needs the table layout itself to be embedding-aware; a
    non-WinAnsi table cell still renders ``?`` here (logged for the manager,
    deferred-work.md MEDIUM). A pure-base-14 block is returned unchanged
    (identity), so the all-Latin corpus stays byte-identical.
    """
    from inkmd.embedded import split_runs_for_embedding

    out: list[RenderedBlock] = []
    for block in blocks:
        new_runs = tuple(
            split_runs_for_embedding(list(block.runs), embedded_ref, missing)
        )
        new_markers = tuple(
            split_runs_for_embedding(
                list(block.marker_runs), embedded_ref, missing
            )
        )
        if new_runs == block.runs and new_markers == block.marker_runs:
            out.append(block)
        else:
            out.append(replace(block, runs=new_runs, marker_runs=new_markers))
    return out


def _render_block(
    block, family: FontFamily, depth: int,
    content_width: float = DEFAULT_CONTENT_WIDTH,
    *,
    body_size: float = BODY_SIZE,
    line_spacing: float = TABLE_LINE_HEIGHT_RATIO,
    table_overflow: str = "wrap",
    table_panel_min_chars: int = TABLE_PANEL_MIN_CHARS,
    usable_height: float = DEFAULT_USABLE_HEIGHT,
) -> list[RenderedBlock]:
    """Lower one AST block (recursively for lists) to flat RenderedBlocks."""
    if isinstance(block, Heading):
        return [_render_heading(block, family, body_size=body_size)]
    if isinstance(block, Paragraph):
        # An image-only paragraph (modulo whitespace text) becomes a
        # block-level image. Mixed-with-text images stay inline and use
        # the alt-text fallback inside _render_inline.
        from inkmd.image_loader import ImageData
        single_image = _paragraph_as_image(block)
        if single_image is not None:
            if isinstance(single_image.resolved, ImageData):
                return [_render_image_block(single_image, content_width)]
            return [RenderedBlock(runs=tuple(
                _render_paragraph(block, family, body_size=body_size)
            ))]
        # Figure idiom: a lead image plus a caption (`<img><br>caption`).
        # Render the image as a block, the caption as a following paragraph.
        # Only split when the image actually embeds; otherwise fall through
        # so the whole paragraph (image alt + caption) stays one inline flow.
        figure = _paragraph_as_figure(block)
        if figure is not None and isinstance(figure[0].resolved, ImageData):
            image, caption_inlines = figure
            caption_runs = _flatten(caption_inlines, family, family.regular, body_size)
            blocks = [_render_image_block(image, content_width)]
            if caption_runs:
                blocks.append(RenderedBlock(
                    runs=tuple(caption_runs),
                    space_above=2.0,
                    space_below=_IMAGE_SPACE_BELOW,
                ))
            return blocks
        return [RenderedBlock(runs=tuple(
            _render_paragraph(block, family, body_size=body_size)
        ))]
    if isinstance(block, List):
        return _render_list(
            block, family, depth, content_width,
            body_size=body_size, line_spacing=line_spacing,
            table_overflow=table_overflow,
            table_panel_min_chars=table_panel_min_chars,
            usable_height=usable_height,
        )
    if isinstance(block, BlockQuote):
        return _render_blockquote(
            block, family, depth, content_width,
            body_size=body_size, line_spacing=line_spacing,
            table_overflow=table_overflow,
            table_panel_min_chars=table_panel_min_chars,
            usable_height=usable_height,
        )
    if isinstance(block, CodeBlock):
        return [_render_code_block(block, family, body_size=body_size)]
    if isinstance(block, Table):
        return _render_table(
            block, family, content_width,
            body_size=body_size, line_spacing=line_spacing,
            table_overflow=table_overflow,
            table_panel_min_chars=table_panel_min_chars,
            usable_height=usable_height,
        )
    if isinstance(block, ThematicBreak):
        return [_render_thematic_break()]
    if isinstance(block, PageBreak):
        # An empty block carrying only the page-break signal: no runs, no
        # spacing, no shapes. The paginator reads page_break and flushes.
        return [RenderedBlock(runs=(), page_break=True)]
    if isinstance(block, HtmlBlock):
        return _render_html_block(block, family, body_size=body_size)
    raise NotImplementedError(f"render: unsupported block {type(block).__name__}")


# HTML block tags whose ENTIRE content is non-document (scripts, styles,
# comments, etc.): their bodies are dropped, not text-extracted.
_HTML_BLOCK_DROP_TAGS = ("script", "style", "textarea")


def _html_block_to_text(raw: str) -> str:
    """Extract readable text from a block-level raw HTML region.

    PDF output has no HTML engine, so block HTML degrades to its text
    content (matching the inline-HTML allow-list philosophy in
    html_filter): comments / CDATA / processing instructions / DOCTYPE
    declarations and the bodies of <script>/<style>/<textarea> are
    dropped entirely (they are not document content); every other tag's
    syntax is stripped and its enclosed text kept. Whitespace runs are
    collapsed so the result reads as a single flowing paragraph.
    """
    s = raw
    # Drop comments, CDATA, PIs, and declarations (incl. <!DOCTYPE>).
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.DOTALL)
    s = re.sub(r"<!\[CDATA\[.*?\]\]>", " ", s, flags=re.DOTALL)
    s = re.sub(r"<\?.*?\?>", " ", s, flags=re.DOTALL)
    s = re.sub(r"<![^>]*>", " ", s, flags=re.DOTALL)
    # Drop the bodies of script/style/textarea entirely.
    for tag in _HTML_BLOCK_DROP_TAGS:
        s = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}\s*>",
            " ",
            s,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # An unclosed drop-tag (rare, EOF) drops to end-of-region.
        s = re.sub(
            rf"<{tag}\b[^>]*>.*\Z",
            " ",
            s,
            flags=re.DOTALL | re.IGNORECASE,
        )
    # Strip any remaining tags, keep their text content.
    s = re.sub(r"</?[A-Za-z][^>]*>", " ", s, flags=re.DOTALL)
    # Collapse whitespace.
    s = " ".join(s.split())
    return s


def _render_html_block(
    block: HtmlBlock, family: FontFamily, *, body_size: float = BODY_SIZE,
) -> list[RenderedBlock]:
    """Render a block-level raw HTML region as extracted readable text.

    Emits nothing when the region carries no document text (a pure
    <!-- comment -->, a <script> block, a bare <table> skeleton, etc.).
    """
    text = _html_block_to_text(block.raw)
    if not text:
        return []
    para = Paragraph(inlines=(Text(content=text),))
    return [RenderedBlock(runs=tuple(
        _render_paragraph(para, family, body_size=body_size)
    ))]


def _paragraph_as_image(p: Paragraph) -> "Image | None":
    """Return the single Image in this paragraph if the paragraph is
    "just an image" (one Image plus optional pure-whitespace text).

    Mixed-content paragraphs (image with surrounding prose) return None
    so the image falls back to its inline alt-text rendering. v0.2
    supports block-level image rendering only; inline images remain a
    v0.3 candidate.
    """
    image = None
    for inline in p.inlines:
        if isinstance(inline, Image):
            if image is not None:
                return None  # more than one image; not block-level
            image = inline
        elif isinstance(inline, Text):
            if inline.content.strip():
                return None  # non-whitespace surrounding text
        else:
            return None  # any other inline (Strong, Code, ...) -> inline
    return image


def _paragraph_as_figure(p: Paragraph):
    """Recognise a "figure" paragraph: a leading block image followed by a
    caption, the `<p align><img><br>caption</p>` idiom GitHub READMEs use.

    Returns ``(image, caption_inlines)`` when the paragraph is optional
    leading whitespace, then exactly one Image, then a HardBreak, then any
    caption content (which may itself contain links, emphasis, more breaks).
    The image renders as a block; the caption renders as a following
    paragraph that inherits the image's alignment. Returns None for anything
    that isn't this shape — in particular a bare image-only paragraph
    (handled by _paragraph_as_image) or an image with prose before it.
    """
    seen_image = None
    rest_start = None
    for idx, inline in enumerate(p.inlines):
        if seen_image is None:
            if isinstance(inline, Image):
                seen_image = inline
            elif isinstance(inline, Text) and not inline.content.strip():
                continue  # leading whitespace before the image is fine
            else:
                return None  # content before the image → not a lead figure
        else:
            # First inline after the image must be the caption separator.
            if isinstance(inline, HardBreak):
                rest_start = idx + 1
                break
            if isinstance(inline, Text) and not inline.content.strip():
                continue  # whitespace between image and break
            return None  # image immediately followed by prose → inline case
    if seen_image is None or rest_start is None:
        return None
    caption = tuple(p.inlines[rest_start:])
    # A caption that is only whitespace/breaks isn't a caption — treat the
    # paragraph as a plain (lone) image instead so _paragraph_as_image wins.
    if not any(
        (isinstance(c, Text) and c.content.strip()) or not isinstance(c, (Text, HardBreak))
        for c in caption
    ):
        return None
    return seen_image, caption


# v0.2 block-level image rendering.
#
# A block-level image occupies its own RenderedBlock via the
# ``prepositioned`` path. We compute the image's display dimensions
# (natural pixel size at 72 dpi, capped to the available column width),
# build an ImagePlacement at the block's origin, and stash the source
# bytes for later XObject emission via _paragraph_image_registry.

# Natural pixels-to-points conversion. PDF uses 72 points per inch; we
# assume images supply 72 DPI by default, matching what every major
# markdown-to-HTML renderer does.
_PIXEL_TO_POINT = 1.0

# Vertical breathing room around a block-level image, in points.
_IMAGE_SPACE_ABOVE = 6.0
_IMAGE_SPACE_BELOW = 6.0

# Approximate column width used by the renderer when sizing images.
# The paginator scales further to the actual available width per page;
# this is the initial guess.
def _render_image_block(
    image, content_width: float = DEFAULT_CONTENT_WIDTH
) -> RenderedBlock:
    """Build a prepositioned RenderedBlock for a block-level image.

    The prepositioned_shapes carry a single dict with ``kind="image"``;
    the paginator translates it to a layout.ImagePlacement at emit time.
    ``content_width`` caps the displayed width to the page's text column.
    """
    data = image.resolved
    # Base size: natural pixel size at 72 dpi. An HTML `width=` provides a
    # requested display width (in points); honour it but never let it
    # exceed the text column. Height follows from the source aspect ratio
    # so images are never distorted. With no requested width, fall back to
    # natural size (also capped to the column).
    nat_w = data.width * _PIXEL_TO_POINT
    nat_h = data.height * _PIXEL_TO_POINT
    aspect = (nat_h / nat_w) if nat_w > 0 else 0.0

    requested = getattr(image, "display_width", None)
    target_w = requested if (requested and requested > 0) else nat_w
    disp_w = min(target_w, content_width) if content_width > 0 else target_w
    disp_h = disp_w * aspect

    # Horizontal placement within the text column. Left is the default;
    # center / right shift the image by the slack between its width and the
    # column. The layout adds this x_offset to the block's left edge.
    slack = max(0.0, content_width - disp_w)
    align = getattr(image, "align", None)
    if align == "center":
        x_offset = slack / 2.0
    elif align == "right":
        x_offset = slack
    else:
        x_offset = 0.0

    # Identifier for the XObject registry: use the URL when available.
    image_id = image.url or f"image:{id(image)}"

    return RenderedBlock(
        runs=(),
        space_above=_IMAGE_SPACE_ABOVE,
        space_below=_IMAGE_SPACE_BELOW,
        prepositioned=True,
        prepositioned_lines=(),
        prepositioned_line_heights=(),
        prepositioned_shapes=(
            {
                "kind": "image",
                "image_id": image_id,
                "image_data": data,  # ImageData; carries format, width, height, bytes
                "rel_y_top": 0.0,
                "x_offset": x_offset,
                "width": disp_w,
                "height": disp_h,
            },
        ),
    )


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


def _render_blockquote(
    quote: BlockQuote, family: FontFamily, depth: int,
    content_width: float = DEFAULT_CONTENT_WIDTH,
    *,
    body_size: float = BODY_SIZE,
    line_spacing: float = TABLE_LINE_HEIGHT_RATIO,
    table_overflow: str = "wrap",
    table_panel_min_chars: int = TABLE_PANEL_MIN_CHARS,
    usable_height: float = DEFAULT_USABLE_HEIGHT,
) -> list[RenderedBlock]:
    """Flatten a BlockQuote: render inner blocks with extra indent + left rule.

    Each nesting level adds one rule at its own x position. Inner-quote
    rules sit to the *right* of outer-quote rules so a `> > >` source
    produces three rules side-by-side, indented progressively.
    """
    # Content inside the quote is indented by QUOTE_INDENT_PT, so the
    # width available to inner tables/images shrinks accordingly.
    inner_width = max(1.0, content_width - QUOTE_INDENT_PT)
    inner: list[RenderedBlock] = []
    for child in quote.blocks:
        inner.extend(_render_block(
            child, family, depth, inner_width,
            body_size=body_size, line_spacing=line_spacing,
            table_overflow=table_overflow,
            table_panel_min_chars=table_panel_min_chars,
            usable_height=usable_height,
        ))
    out: list[RenderedBlock] = []
    for cb in inner:
        # Our new rule sits at the outermost x relative to inner blocks.
        # Inner rules (already in cb.left_rules) get shifted right by
        # QUOTE_INDENT_PT to make room for our rule on their left.
        shifted_inner = tuple(r + QUOTE_INDENT_PT for r in cb.left_rules)
        new_rules = (QUOTE_RULE_OFFSET_PT,) + shifted_inner
        # Preserve every field of the inner block (notably the
        # ``prepositioned_*`` payload — a table or image inside a quote
        # used to be silently dropped because this reconstruction listed
        # only a subset of fields) while adding our indent and rule. The
        # layout layer applies ``body_indent`` to prepositioned content,
        # so the table/image shifts right with the quote body.
        out.append(
            replace(
                cb,
                body_indent=cb.body_indent + QUOTE_INDENT_PT,
                marker_x=cb.marker_x + QUOTE_INDENT_PT,
                left_rules=new_rules,
                left_rule_fill=QUOTE_RULE_FILL,
            )
        )
    return out


def _render_table(
    table: Table, family: FontFamily, content_width: float = DEFAULT_CONTENT_WIDTH,
    *,
    body_size: float = BODY_SIZE,
    line_spacing: float = TABLE_LINE_HEIGHT_RATIO,
    table_overflow: str = "wrap",
    table_panel_min_chars: int = TABLE_PANEL_MIN_CHARS,
    usable_height: float = DEFAULT_USABLE_HEIGHT,
) -> list[RenderedBlock]:
    """Lower a Table to one or more pre-positioned ``RenderedBlock``s.

    Strategy: compute per-column widths from natural content widths, then
    branch on ``table_overflow`` for a table too wide for ``content_width``:

    - A table that FITS renders exactly as before, BYTE-IDENTICAL in every
      mode -- one block over all columns at natural (slacked) widths.
    - ``"wrap"`` (default) splits the columns into page-width groups and
      returns ONE block PER GROUP: each is a full table strip over a subset
      of columns, with column 0 repeated as the key column and a faint
      ``(continued)`` marker above continuation panels. Each panel packs as
      densely as it readably can -- columns count toward the panel budget at
      a floor of ``table_panel_min_chars`` character widths, then each panel
      is shrunk to fit (cells wrap), so a panel holds many more columns than
      packing at natural width would allow. Each panel is an independent
      block the paginator places + splits on its own, so each panel's own
      header repeats on its own continuation page. Markdown has no notion of
      a key column; repeating column 0 is a deliberate convention (the
      leftmost column is the row label in most data tables).
    - ``"shrink"`` keeps the pre-0.5 behaviour: squeeze columns toward their
      minimum and overflow the right edge silently. ``"warn"`` does the same
      and emits one :class:`TableOverflowWarning`. ``"error"`` raises
      :class:`TableOverflowError`.
    - A single column wider than the whole text column (an unbreakable
      monster cell) cannot be wrapped into panels, so ``"wrap"`` falls back
      to shrink + a :class:`TableOverflowWarning` for that table.

    Returns a list so a multi-panel wrap flows through ``blocks.extend`` in
    ``render_document`` with no signature change; the non-wrap cases return
    a one-element list. The layout layer translates the relative coordinates
    to absolute page coordinates at pagination time.
    """
    n_cols = len(table.headers)
    if n_cols == 0:
        return [RenderedBlock(runs=())]

    # Lower every cell's inlines to a list of Runs. Headers are bold. Cell
    # text renders at the effective body size so a table scales with the rest
    # of the document.
    def cell_runs(cell: TableCell, bold: bool) -> list[Run]:
        font = family.bold if bold else family.regular
        runs: list[Run] = []
        for inline in cell.inlines:
            runs.extend(_render_inline(inline, family, font=font, size=body_size))
        return runs

    header_runs = [cell_runs(c, bold=True) for c in table.headers]
    body_runs = [
        [cell_runs(c, bold=False) for c in row] for row in table.rows
    ]

    # 1. Natural column widths: max over header + body, of the unwrapped
    #    cell width (no padding, no border). Emoji runs measure as their
    #    box width so an emoji-bearing cell isn't undersized (the run's
    #    text is the raw emoji char, which would otherwise measure as ~0).
    def runs_natural_width(runs: list[Run]) -> float:
        total = 0.0
        for r in runs:
            if r.emoji is not None:
                total += emoji_box(r.size, r.emoji.aspect)[0]
            else:
                total += text_width(r.text, r.font, r.size)
        return total

    natural = [0.0] * n_cols
    for i, runs in enumerate(header_runs):
        natural[i] = max(natural[i], runs_natural_width(runs))
    for row in body_runs:
        for i, runs in enumerate(row):
            natural[i] = max(natural[i], runs_natural_width(runs))

    # 2. Available content width per cell = column_width - 2 × padding.
    #    Total cell content width budget = available - n_cols × 2 padding.
    available_total = content_width
    padding_total = n_cols * 2 * TABLE_CELL_PADDING_X
    content_budget = available_total - padding_total

    # Each column's minimum is the width of its widest single token —
    # below that, wrapping can't help and the longest word overflows
    # the cell. This is the only minimum the shrinker MUST respect.
    min_widths = [_widest_token_width(header_runs[i], body_runs, i)
                  for i in range(n_cols)]

    # Row leading scales with both the body size (S2) and the line-spacing
    # multiplier (S3), so a table breathes with the same knob as prose. At
    # the defaults (body 12, spacing 1.2) this is 14.4, exactly as before.
    line_height = body_size * line_spacing

    # Height floor on each column's minimum width. A too-wide table is fitted
    # by shrinking columns and wrapping their cells; but if a column is shrunk
    # so narrow that its tallest cell wraps to more lines than a page can hold,
    # every OTHER cell in that row is stranded on line 1 of a row taller than
    # the page -- the data reads as a tower with the rest pushed off the bottom.
    # So no column may be shrunk narrower than the width at which its tallest
    # cell fits the per-row line budget. The header repeats on each page-slice,
    # so the data row only gets the lines left after the header. The line count
    # is monotonic in width (wider -> fewer wrap lines), so the floor is found
    # by binary search using the real wrap function. A column whose tallest
    # cell cannot fit even at content_width (a single cell longer than a page)
    # caps at content_width: that row genuinely exceeds a page and the S6f
    # group slicing spills it across pages -- lossless. In wrap mode this cap
    # is further bounded by the block's width budget at emit time
    # (_cap_height_floored_mins), so the floor never pushes a table off the
    # right edge of the page; shrink/warn keep the raw floored minimums.
    def _line_count(runs: list[Run], width: float) -> int:
        if not runs:
            return 1
        return len(wrap_runs(runs, max(width, 1.0))) or 1

    # Budget: the header row plus ONE data row must fit one page. Either row
    # can be driven by the same (e.g. key) column, so giving each row half the
    # page's lines guarantees their sum fits regardless of which column is
    # tallest -- the header-cell-is-the-tall-one case included. For ordinary
    # tables (one-line headers, short cells) this budget is far more than
    # needed, so the floor never binds and nothing changes.
    #
    # line_height can be 0 in the degenerate line_spacing=0 case; there is no
    # meaningful "lines per page" then (a zero-height row never overflows), so
    # skip the height floor and keep the existing token minimums.
    apply_height_floor = line_height > 0 and usable_height > 0
    total_lines = max(1, int(usable_height // line_height)) if apply_height_floor else 1
    row_line_budget = max(1, total_lines // 2)

    def _tallest_cell(col: int) -> list[Run]:
        # The cell in this column that wraps to the most lines at any given
        # width is the one with the greatest natural (unwrapped) width, since
        # line count is monotonic in content length at a fixed width. Pick it
        # once so the binary search re-wraps a single cell, not the whole
        # column. Header counts as a cell (it can be the tall one, e.g. a long
        # key header).
        best = header_runs[col]
        best_w = runs_natural_width(best)
        for r in range(len(body_runs)):
            cell = body_runs[r][col]
            w = runs_natural_width(cell)
            if w > best_w:
                best, best_w = cell, w
        return best

    def _height_floor(col: int) -> float:
        # The narrowest width at which column ``col``'s tallest cell wraps to
        # <= row_line_budget lines. Binary-search width in [widest_token,
        # content_width] on that one cell (line count is monotonic in width).
        cell = _tallest_cell(col)
        lo = min_widths[col]      # never below the widest unbreakable token
        hi = content_width
        # Already fits at the token min? Then no height floor is needed (the
        # common case: short cells wrap to one line well above the budget).
        if _line_count(cell, lo) <= row_line_budget:
            return lo
        # Cannot fit even at full width? Cap at content_width (irreducible
        # case: a cell taller than a page; row-pagination handles it).
        if _line_count(cell, hi) > row_line_budget:
            return hi
        # Binary search for the smallest width that fits the budget. Width is
        # continuous; iterate to ~0.5pt precision (deterministic, bounded).
        for _ in range(24):
            mid = (lo + hi) / 2.0
            if _line_count(cell, mid) <= row_line_budget:
                hi = mid
            else:
                lo = mid
            if hi - lo <= 0.5:
                break
        return hi

    # Fold the height floor into the per-column minimum the shrinker enforces,
    # alongside the existing widest-token minimum. Only columns that would
    # otherwise tower are raised; a short-celled column's tallest cell already
    # fits at its token min, so its floor stays the token min and nothing
    # changes (a fitting table never shrinks, so it never reaches the shrinker
    # at all -- this only affects the shrink + panel paths).
    #
    # base_min_widths keeps the PRE-height-floor token minimums: wrap mode
    # needs them to cap the floors back when honoring them would push a
    # block past the width budget (S6g, _cap_height_floored_mins). The
    # shrink/warn paths keep using the floored min_widths untouched.
    base_min_widths = list(min_widths)
    if apply_height_floor:
        min_widths = [max(min_widths[i], _height_floor(i)) for i in range(n_cols)]

    PR = _PR  # local alias

    def run_advance(r: Run) -> float:
        if r.emoji is not None:
            return emoji_box(r.size, r.emoji.aspect)[0]
        return text_width(r.text, r.font, r.size)

    def emit_block(col_indices, content_widths_local, continued, space_below):
        """Build ONE table block over a subset of columns (a panel).

        ``col_indices`` are ORIGINAL column indices in panel-display order;
        ``content_widths_local`` is the content width for each, in the same
        order. The cell text, alignment, and bold/regular styling come from
        the original column; only the geometry (x positions, wrap widths) is
        panel-local. Called with all columns + the fit/shrink content widths
        for the normal path (byte-identical to pre-S6), and once per group
        with full natural widths for the panel-wrap path.

        ``continued`` adds a faint ``(continued)`` line above the header so a
        reader knows this panel continues the previous one's rows (panels
        2..N). ``space_below`` sets the block's bottom breathing room (used to
        open the inter-panel gap). Returns a ``RenderedBlock``.
        """
        n_local = len(col_indices)
        # Column widths include left + right padding; x positions are the
        # left edge of each column relative to the panel's left edge.
        col_widths = [w + 2 * TABLE_CELL_PADDING_X for w in content_widths_local]
        col_x: list[float] = []
        x = 0.0
        for cw in col_widths:
            col_x.append(x)
            x += cw
        table_width = x

        # Wrap every cell to its column's content width and measure heights.
        def wrap_cell(runs: list[Run], j: int) -> list[list[Run]]:
            if not runs:
                return [[]]
            return wrap_runs(runs, content_widths_local[j]) or [[]]

        header_lines = [
            wrap_cell(header_runs[col_indices[j]], j) for j in range(n_local)
        ]
        body_lines = [
            [wrap_cell(row[col_indices[j]], j) for j in range(n_local)]
            for row in body_runs
        ]

        def row_height(cell_lines_per_col: list[list[list[Run]]]) -> float:
            max_lines = max((len(c) for c in cell_lines_per_col), default=1)
            return max_lines * line_height + 2 * TABLE_CELL_PADDING_Y

        header_h = row_height(header_lines)
        body_heights = [row_height(row) for row in body_lines]

        # y positions (relative to panel top, y growing downward here; the
        # layout flips when placing).
        row_tops = [0.0]
        row_tops.append(header_h)
        for h in body_heights[:-1]:
            row_tops.append(row_tops[-1] + h)
        total_height = header_h + sum(body_heights)

        def emit_cell_local(cell_lines, j, alignment, lines_out, shapes_out):
            """Emit one cell's lines/shapes in ROW-LOCAL coords (y from row top).

            ``j`` is the panel-local column position; geometry reads col_x[j]
            and content_widths_local[j], content has already been selected.
            """
            x_left = col_x[j] + TABLE_CELL_PADDING_X
            cell_content_w = content_widths_local[j]
            baseline_y_from_top = TABLE_CELL_PADDING_Y + line_height
            for li, line in enumerate(cell_lines):
                line_w = sum(run_advance(r) for r in line)
                if alignment == "center":
                    x_start = x_left + (cell_content_w - line_w) / 2.0
                elif alignment == "right":
                    x_start = x_left + (cell_content_w - line_w)
                else:
                    x_start = x_left
                # Left overflow is corruption (flings glyphs across the grid
                # line); right overflow is acceptable. Clamp to the cell edge.
                if x_start < x_left:
                    x_start = x_left
                runs_record: list[_PR] = []
                cx = x_start
                baseline = baseline_y_from_top + li * line_height
                for run in line:
                    if run.emoji is not None:
                        e_w, e_h = emoji_box(run.size, run.emoji.aspect)
                        descent = e_h * EMOJI_BASELINE_DROP
                        rel_y_top = baseline - (e_h - descent)
                        shapes_out.append({
                            "kind": "image",
                            "image_id": run.emoji.image_id,
                            "image_data": run.emoji.image_data,
                            "rel_y_top": rel_y_top,
                            "x_offset": cx,
                            "width": e_w,
                            "height": e_h,
                        })
                        cx += e_w
                        continue
                    runs_record.append(PR(
                        text=run.text, x_rel=cx, y_from_top=baseline,
                        font=run.font, size=run.size, link_url=run.link_url,
                        color=run.color, strike=run.strike, y_shift=run.y_shift,
                        background_fill=run.background_fill,
                        border_fill=run.border_fill, underline=run.underline,
                    ))
                    cx += text_width(run.text, run.font, run.size)
                if runs_record:
                    lines_out.append((baseline, tuple(runs_record)))

        def build_group(cells_per_col, height, is_header, tint, top_rule=True):
            """One row group (header or a body row) in row-local coordinates:
            optional background tint, the cell content, and the top horizontal
            rule. Vertical grid segments + the group's bottom rule are drawn by
            the layout per page-slice (they depend on how groups stack).

            ``top_rule=False`` is used by the oversized-group slicer for
            continuation chunks: a chunk that continues a cell from the
            previous page must not draw a horizontal rule through the middle
            of that cell."""
            lines_out: list = []
            shapes_out: list = []
            if tint is not None:
                shapes_out.append({
                    "kind": "fill", "rel_y_top": 0.0, "height": height,
                    "x_offset": 0.0, "width": table_width, "fill": tint,
                })
            # Top horizontal rule for this group (so per-page slices get row
            # separators without the layout knowing the table's row structure).
            if top_rule:
                shapes_out.append({
                    "kind": "fill", "rel_y_top": -TABLE_GRID_WIDTH / 2.0,
                    "height": TABLE_GRID_WIDTH, "x_offset": 0.0,
                    "width": table_width, "fill": TABLE_GRID_FILL,
                })
            for j in range(n_local):
                emit_cell_local(cells_per_col[j], j,
                                table.alignments[col_indices[j]],
                                lines_out, shapes_out)
            return {
                "height": height,
                "is_header": is_header,
                "lines": tuple(lines_out),
                "shapes": tuple(shapes_out),
            }

        # Full (unchunked) groups. These are ALWAYS built: the flattened
        # single-block view below is derived from them so its per-row rules
        # never land mid-cell, and on the common path (nothing oversized)
        # they are also exactly what the paginator gets.
        header_group = build_group(header_lines, header_h, True, TABLE_HEADER_BG)
        body_groups = [
            build_group(body_lines[r], body_heights[r], False, None)
            for r in range(len(body_lines))
        ]

        # --- Oversized-group slicing (S6f) ---------------------------------
        # The paginator places header and row groups ATOMICALLY: a group
        # taller than the room a fresh page slice can give it is drawn once
        # and everything past the bottom edge lands outside the media box,
        # invisible to every PDF reader. So any group that cannot fit a fresh
        # slice is pre-split HERE, at line boundaries, into chunk groups the
        # paginator's existing row-boundary loop handles unchanged.
        #
        # Cut rule: all cells in a table share one line grid (baselines at
        # TABLE_CELL_PADDING_Y + (i+1)*line_height from the group top), so a
        # chunk takes whole grid lines [a, b) and is rebuilt EXACTLY like a
        # fresh row group over those lines: height (b-a)*line_height +
        # 2*TABLE_CELL_PADDING_Y, baselines re-seated on the same grid. No
        # glyph's ink straddles a cut because every line goes whole into one
        # chunk, with TABLE_CELL_PADDING_Y + line_height above its first
        # baseline (clears ascenders) and TABLE_CELL_PADDING_Y below its last
        # (clears descenders, same clearance a normal row bottom has). The
        # tint fill is rebuilt per chunk, so it is clipped to the chunk
        # window for free; an emoji image shape is emitted by its line, so it
        # goes whole into the chunk containing its top. Chunks after the
        # first carry no top rule (no rule through the middle of a cell).
        #
        # Chunks are sized to fit ANY fresh slice they can land on, including
        # the first slice of a continuation panel (which reserves one
        # line_height above the box for the "(continued)" label), with one
        # further line_height of headroom so a chunk never sits on an exact
        # float boundary of the slice.
        label_reserve = line_height if continued else 0.0
        fresh_page_room = usable_height - label_reserve
        slicing_on = line_height > 0 and usable_height > 0

        def group_chunks(cells_per_col, height, is_header, tint, budget):
            """One group when it fits ``budget``, else line-grid chunks that
            each do. Returns (groups, sliced_flag)."""
            if not slicing_on or height <= budget:
                return (
                    [build_group(cells_per_col, height, is_header, tint)],
                    False,
                )
            # Whole lines per chunk, conservative by one line of headroom.
            per_chunk = max(1, int(
                (budget - 2 * TABLE_CELL_PADDING_Y - line_height)
                // line_height
            ))
            n_lines = max((len(c) for c in cells_per_col), default=1)
            chunks = []
            for a in range(0, n_lines, per_chunk):
                b = min(a + per_chunk, n_lines)
                chunk_h = (b - a) * line_height + 2 * TABLE_CELL_PADDING_Y
                chunks.append(build_group(
                    [c[a:b] for c in cells_per_col], chunk_h, is_header,
                    tint, top_rule=(a == 0),
                ))
            return chunks, True

        # Header demotion is decided FIRST, so the body-row chunk budget is
        # computed with the EFFECTIVE header height (0 when demoted) and
        # never goes negative on small pages. A header taller than the page
        # cannot usefully repeat per slice (re-drawing it would leave a data
        # row no page with room, burying the data forever), so it is demoted
        # to no-repeat: rendered ONCE as leading pseudo-row chunks carrying
        # the header tint, sliced like any oversized row but against the full
        # fresh-slice room since nothing repeats above them. Later pages then
        # carry no column labels; render-once is strictly better than
        # repeat-forever-and-bury-the-data.
        header_repeats = (not slicing_on) or header_h <= usable_height
        sliced = False
        if header_repeats:
            paginator_header = header_group
            leading_groups: list[dict] = []
            row_budget = fresh_page_room - header_h
        else:
            # Empty header group: the paginator's per-slice header redraw
            # becomes a no-op (no lines, no shapes, zero height), so no
            # repetition and no stray rules for the absent header.
            paginator_header = {
                "height": 0.0, "is_header": True, "lines": (), "shapes": (),
            }
            leading_groups, _ = group_chunks(
                header_lines, header_h, True, TABLE_HEADER_BG,
                fresh_page_room,
            )
            sliced = True
            row_budget = fresh_page_room

        paginator_rows: list[dict] = list(leading_groups)
        for r in range(len(body_lines)):
            if not slicing_on or body_heights[r] <= row_budget:
                # Fits a fresh slice: reuse the already-built full group, so
                # a table with nothing oversized hands the paginator the
                # exact same objects as before (byte-identical output).
                paginator_rows.append(body_groups[r])
                continue
            row_chunks, _ = group_chunks(
                body_lines[r], body_heights[r], False, None, row_budget,
            )
            paginator_rows.extend(row_chunks)
            sliced = True

        # Continuation marker: a continuation panel (panels 2..N) carries a
        # faint "(continued)" label. It is NOT folded into the table box here:
        # the paginator draws it in the clear gap ABOVE the panel, so neither
        # the horizontal top rule nor the vertical column rules (which span the
        # whole table slice from its top down) can cross the word. The panel's
        # BOX geometry (header group, row tops, total height) is therefore
        # identical to a normal panel's; only the meta flag differs. The
        # normal/shrink/fits path passes continued=False, so its output is
        # untouched and a fitting table stays byte-identical.
        table_meta = {
            "table_width": table_width,
            "col_x": tuple(col_x),
            "grid_width": TABLE_GRID_WIDTH,
            "grid_fill": TABLE_GRID_FILL,
            "line_height": line_height,
            "header": paginator_header,
            "rows": tuple(paginator_rows),
            # Whether the header group repeats per page slice. False only
            # for a demoted (page-tall, no-repeat) header; the paginator
            # needs no flag (the demoted header group is empty, so its
            # per-slice redraw is a no-op), this is for introspection.
            "header_repeats": header_repeats,
            "continued": continued,
            # The label the paginator draws in the gap above a continuation
            # panel. Carried as a fully-specified run (text/font/size/colour
            # decided here, in the render layer) plus its x offset from the
            # panel's left edge, so the layout layer only positions it and
            # need not import render. None for non-continuation panels.
            "continued_label": (
                {
                    "text": TABLE_CONTINUED_LABEL,
                    "font": family.regular,
                    "size": body_size,
                    "color": TABLE_GRID_FILL,
                    "x_offset": TABLE_CELL_PADDING_X,
                }
                if continued
                else None
            ),
        }

        # Flattened single-block view (table-top coords) for the atomic fast
        # path + PDF emitter. Derived from the FULL (unchunked) groups so the
        # two views never drift and its per-row rules never land mid-cell;
        # the layout prefers prepositioned_table when present, so the sliced
        # groups are what actually paginate.
        positioned_lines: list[tuple[float, tuple]] = []
        shapes: list[dict] = []

        def stack_group(group: dict, top: float) -> None:
            for baseline, runs in group["lines"]:
                shifted = tuple(
                    replace(pr, y_from_top=pr.y_from_top + top) for pr in runs
                )
                positioned_lines.append((baseline + top, shifted))
            for sh in group["shapes"]:
                s = dict(sh)
                s["rel_y_top"] = sh["rel_y_top"] + top
                shapes.append(s)

        stack_group(header_group, 0.0)
        for r, group in enumerate(body_groups):
            stack_group(group, row_tops[r + 1])

        # Horizontal grid rules: top, below header, between & below body rows.
        h_lines_y = [0.0, header_h]
        cumulative = header_h
        for h in body_heights:
            cumulative += h
            h_lines_y.append(cumulative)
        for y_top in h_lines_y:
            shapes.append({
                "kind": "fill", "rel_y_top": y_top - TABLE_GRID_WIDTH / 2.0,
                "height": TABLE_GRID_WIDTH, "x_offset": 0.0,
                "width": table_width, "fill": TABLE_GRID_FILL,
            })
        # Vertical grid rules: left edge of each column plus the right edge.
        for vx in list(col_x) + [table_width]:
            shapes.append({
                "kind": "fill", "rel_y_top": 0.0, "height": total_height,
                "x_offset": vx - TABLE_GRID_WIDTH / 2.0,
                "width": TABLE_GRID_WIDTH, "fill": TABLE_GRID_FILL,
            })

        return RenderedBlock(
            runs=(),
            space_above=6.0,
            space_below=space_below,
            prepositioned=True,
            prepositioned_lines=tuple(positioned_lines),
            prepositioned_line_heights=(line_height,) * len(positioned_lines),
            prepositioned_shapes=tuple(shapes),
            prepositioned_table=table_meta,
        )

    def table_label() -> str:
        """A short identifier for warnings/errors: position + first header."""
        head = ""
        for r in header_runs[0]:
            head += r.text
        head = head.strip()
        if head:
            return f"table with header {head!r}"
        return "a table"

    natural_sum = sum(natural)
    fits = natural_sum <= content_budget or natural_sum == 0
    if fits:
        # Add small slack to each column's natural width so token-by-token
        # wrap doesn't trigger on borderline-fit content (token widths
        # measured individually sum slightly higher than the joined-string
        # natural width because kerning across word boundaries is lost
        # when splitting on whitespace). 2pt is generous; the table still
        # fits because we only add when budget allows.
        slack = 2.0
        slack_total = slack * n_cols
        if natural_sum + slack_total <= content_budget:
            content_widths = [w + slack for w in natural]
        else:
            content_widths = list(natural)
        # Byte-identical fits path: one block over all columns, no slack to
        # the mode (a fitting table renders the same in every mode).
        return [emit_block(list(range(n_cols)), content_widths, False, 6.0)]

    # Past here the table does NOT fit. Behaviour depends on the mode.
    if table_overflow == "error":
        raise TableOverflowError(
            f"{table_label()} is too wide to fit the text column "
            f"(natural width {natural_sum:.0f}pt exceeds the "
            f"{content_budget:.0f}pt budget); table_overflow='error'"
        )

    def shrink_block(warn: bool):
        """The pre-0.5 path: shrink proportionally, overflow right. One block
        over all columns. Optionally emit a TableOverflowWarning."""
        content_widths = _shrink_to_budget(natural, content_budget, min_widths)
        if warn:
            overflow = sum(content_widths) - content_budget
            warnings.warn(
                f"{table_label()} is too wide to fit and was shrunk; it "
                f"overflows the text column by about {max(overflow, 0.0):.0f}pt",
                TableOverflowWarning, stacklevel=2,
            )
        return [emit_block(list(range(n_cols)), content_widths, False, 6.0)]

    if table_overflow == "shrink":
        return shrink_block(warn=False)
    if table_overflow == "warn":
        return shrink_block(warn=True)

    # table_overflow == "wrap". Panels are the LAST RESORT, not the first
    # response to overflow. A table that is wider than the budget at its
    # natural (one-line) widths can usually still be made to fit on a single
    # strip by shrinking columns and letting the cell text wrap to more lines
    # -- lossless in content, no clipping -- and that reads far better than
    # stacking panels. But "fits on one strip" must mean "fits READABLY", not
    # "fits at one character per column": a dozen-plus columns can squeak
    # under the budget at one char each (padding eats most of the page), and
    # crushing every column to a single glyph -- headers reading vertically,
    # a long token wrapping to one char per line -- is technically lossless
    # but unreadable. So gate on the same readable FLOOR that governs panel
    # packing: each column counts at min(natural, floor) (its natural width if
    # narrower than the floor, else the floor). table_panel_min_chars thus
    # governs BOTH whether and how to panel -- one coherent lever.
    #
    # The floor uses a single representative glyph width -- the width of "0"
    # in the body (regular) font at the body size. "0" is a deterministic,
    # average-ish glyph (a digit is close to the mean advance for both
    # Helvetica and Times); the exact value is not load-bearing, it only sets
    # the floor scale, so a representative char keeps this simple and stable
    # rather than per-column or max-char widths.
    char_w = text_width("0", family.regular, body_size)
    floor_width = table_panel_min_chars * char_w
    floor_mins = [min(natural[i], floor_width) for i in range(n_cols)]
    if sum(floor_mins) <= content_budget:
        # Fits readably on one strip: do exactly what "shrink" mode does --
        # one block, columns shrunk toward their minimum, cells wrapped. This
        # keeps real-world tables (a handful of columns) rendering as a single
        # table, byte for byte as before, instead of being split needlessly.
        if sum(min_widths) <= content_budget:
            return shrink_block(warn=False)
        # The minimums only exceed the budget here when the height floor
        # raised them (floor_mins fit by the gate above, and token mins
        # never exceed floor mins): honoring the floor would overflow the
        # right margin and clip glyphs off the media box. Wrap mode promises
        # losslessness, so cap the floored columns to the leftover after
        # every other column takes its existing minimum (token min raised to
        # the readable floor, same basis the panel path uses). The capped
        # cell wraps taller and the S6f slicing paginates it. shrink/warn
        # keep the old overflow-right behaviour and never reach this.
        strip_base = [
            max(floor_mins[i], base_min_widths[i]) for i in range(n_cols)
        ]
        strip_floored = [
            max(strip_base[i], min_widths[i]) for i in range(n_cols)
        ]
        capped = _cap_height_floored_mins(
            strip_base, strip_floored, content_budget
        )
        content_widths = _shrink_to_budget(natural, content_budget, capped)
        return [emit_block(list(range(n_cols)), content_widths, False, 6.0)]

    # Only here -- where the table cannot fit even with every column at the
    # readable floor -- is it genuinely un-fittable on one strip. Split its
    # columns into page-width panels, packing each panel as densely as it
    # readably can at the same floor, then emit each panel via shrink-to-budget
    # so its columns actually fit and cells wrap.
    groups = _partition_columns(
        natural, content_width, TABLE_CELL_PADDING_X, floor_width
    )
    if groups is None:
        # A single column (with col 0) is itself wider than the budget even at
        # the floor, or a 1-column table overflows. Panels can't help either,
        # so fall back to shrink + a warning (the genuine-monster case; the
        # warning is expected and correct here).
        content_widths = _shrink_to_budget(natural, content_budget, min_widths)
        warnings.warn(
            f"{table_label()} has a column wider than the text column and "
            f"cannot be wrapped into panels; it was shrunk and overflows",
            TableOverflowWarning, stacklevel=2,
        )
        return [emit_block(list(range(n_cols)), content_widths, False, 6.0)]

    blocks: list[RenderedBlock] = []
    last = len(groups) - 1
    for gi, col_indices in enumerate(groups):
        # Emit each panel through the SAME shrink-to-budget the single-table
        # overflow path uses, over this panel's own subset of columns: the
        # panel may hold more columns than fit at natural width (that is the
        # point of packing at the floor), so wide columns are squeezed toward
        # the readable FLOOR and their cells wrap. The per-column minimum is
        # the floor, so a column shrinks no smaller than min(natural, floor):
        # a column narrower than the floor (e.g. the short key column) keeps
        # its natural width instead of being crushed proportionally alongside
        # the wide columns. The widest-token width is kept as a hard lower
        # bound so a single glyph never overflows its cell. The partition
        # packed at this same floor, so sum(floor mins) <= panel_budget by
        # construction -- the panel fits at these widths. The panel budget is
        # the full content width minus this panel's own padding (fewer columns
        # than the whole table -> more room per column).
        panel_naturals = [natural[c] for c in col_indices]
        panel_mins = [
            max(min(natural[c], floor_width), min_widths[c]) for c in col_indices
        ]
        panel_budget = content_width - len(col_indices) * 2 * TABLE_CELL_PADDING_X
        # Height floors are best-effort inside a panel (S6g): a floor raised
        # all the way toward content_width (irreducible page-tall cell, e.g.
        # a giant key-column header) would otherwise push the panel past its
        # budget and off the right edge of the media box, invisible. The
        # capped column takes the leftover after the other columns' token +
        # readable-floor minimums; the taller cell is carried across pages
        # by the S6f slicing. No-op (same list back) when the floors fit, so
        # ordinary panels are byte-identical.
        panel_base = [
            max(min(natural[c], floor_width), base_min_widths[c])
            for c in col_indices
        ]
        panel_mins = _cap_height_floored_mins(
            panel_base, panel_mins, panel_budget
        )
        widths_local = _shrink_to_budget(panel_naturals, panel_budget, panel_mins)
        continued = gi > 0
        # Open the inter-panel gap below every panel except the last.
        space_below = (6.0 + TABLE_PANEL_GAP) if gi < last else 6.0
        blocks.append(emit_block(col_indices, widths_local, continued, space_below))
    return blocks


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
    strike: bool = False
    y_shift: float = 0.0
    background_fill: tuple[float, float, float] | None = None
    border_fill: tuple[float, float, float] | None = None
    underline: bool = False


def _render_code_block(
    cb: CodeBlock, family: FontFamily, *, body_size: float = BODY_SIZE,
) -> RenderedBlock:
    """Lower a CodeBlock to a RenderedBlock with monospace + background fill.

    Fenced code renders at ``body_size / BODY_SIZE * CODE_FONT_SIZE`` so it
    scales with the effective body size while keeping the 0.875 ratio that
    makes it slightly smaller than body. At body_size == BODY_SIZE the ratio
    is exactly 1.0, so the size is exactly CODE_FONT_SIZE (byte-identical).
    """
    code_size = body_size / BODY_SIZE * CODE_FONT_SIZE
    # The paginator uses `preserve_lines=True` to split runs on '\n' rather
    # than wrapping. Emoji are the documented exception to the WinAnsi-`?`
    # rule and must render even in a code block, so route each source line
    # through the emoji splitter (emoji become atomic image runs / fallback
    # labels) and re-join the lines with newline-bearing text runs so the
    # preserve-lines splitter still sees the line structure.
    # CodeBlock.content carries one trailing newline as each line's
    # terminator (the spec convention; both fenced and indented code use it).
    # Drop exactly that single trailing newline before splitting so it does
    # not render as a phantom empty final line; genuine interior/trailing
    # blank lines (content ending in two-or-more newlines) are preserved.
    body = cb.content[:-1] if cb.content.endswith("\n") else cb.content
    line_texts = body.split("\n")
    run_list: list[Run] = []
    for idx, line_text in enumerate(line_texts):
        if idx > 0:
            run_list.append(Run(text="\n", font=family.monospace, size=code_size))
        run_list.extend(split_text_into_runs(
            line_text, font=family.monospace, size=code_size,
            link_url=None, color=None, strike=False,
        ))
    runs = tuple(run_list)
    return RenderedBlock(
        runs=runs,
        space_above=6.0,
        space_below=6.0,
        body_indent=CODE_PADDING_PT,
        background_fill=CODE_BG_FILL,
        bg_padding=CODE_PADDING_PT,
        preserve_lines=True,
    )


def _render_list(
    lst: List, family: FontFamily, depth: int,
    content_width: float = DEFAULT_CONTENT_WIDTH,
    *,
    body_size: float = BODY_SIZE,
    line_spacing: float = TABLE_LINE_HEIGHT_RATIO,
    table_overflow: str = "wrap",
    table_panel_min_chars: int = TABLE_PANEL_MIN_CHARS,
    usable_height: float = DEFAULT_USABLE_HEIGHT,
) -> list[RenderedBlock]:
    """Flatten a List into a sequence of RenderedBlocks.

    Each item's first body-block carries the marker prefix and the
    item's body_indent. Subsequent body-blocks of the same item share
    the body_indent but have no marker. Nested lists recurse at deeper
    indent. Markers render at the effective body size so they scale with
    the item text.
    """
    out: list[RenderedBlock] = []
    marker_x = LIST_INDENT_PT * depth
    # The body sits one indent step past the marker by default, but an
    # ordered list whose markers reach two-plus digits ("10. ", "100. ")
    # needs a wider slot or the marker overruns and overlaps the body
    # text. Size the slot to the WIDEST marker in this list (the largest
    # number is the last item) plus a small gap, falling back to the
    # standard step for short markers. This is per-list, so a 1..9 list
    # keeps the tight default and a 1..120 list widens uniformly.
    default_indent = LIST_INDENT_PT * (depth + 1)
    if lst.ordered and lst.items:
        widest_marker = f"{lst.start + len(lst.items) - 1}. "
        marker_w = text_width(widest_marker, family.regular, body_size)
        indent_for_items = max(default_indent, marker_x + marker_w + MARKER_BODY_GAP)
    else:
        indent_for_items = default_indent

    item_spacing = LOOSE_ITEM_SPACING if not lst.tight else TIGHT_ITEM_SPACING

    for item_idx, item in enumerate(lst.items):
        # GFM task-list items replace the bullet/number with a checkbox
        # marker. Plain ASCII keeps the glyph available in every WinAnsi
        # font, so users don't see a tofu box on Helvetica systems.
        if item.task is None:
            marker_text = _marker_text(lst, item_idx)
        elif item.task:
            marker_text = "[x] "
        else:
            marker_text = "[ ] "
        marker_runs = (Run(text=marker_text, font=family.regular, size=body_size),)

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
            child_width = max(1.0, content_width - indent_for_items)
            child_blocks = _render_block(
                child, family, depth + 1, child_width,
                body_size=body_size, line_spacing=line_spacing,
                table_overflow=table_overflow,
                table_panel_min_chars=table_panel_min_chars,
                usable_height=usable_height,
            )
            # A nested list computes its own absolute indent from its
            # deeper depth, so it must NOT have this item's indent added
            # on top. Every other child block (paragraph, code, image,
            # thematic break) carries only intrinsic padding relative to
            # its container, so it needs the item's indent added to sit
            # under the item body.
            child_is_list = isinstance(child, List)
            for cb_idx, cb in enumerate(child_blocks):
                # Preserve ALL of the child block's fields (preserve_lines,
                # background_fill, bg_padding, left_rules, and the whole
                # prepositioned* family for images/tables) and override only
                # the list-specific positioning. Reconstructing a fresh
                # RenderedBlock with a hand-picked subset of fields silently
                # dropped code-block backgrounds, code line-preservation,
                # and nested block images.
                item_indent = cb.body_indent if child_is_list else cb.body_indent + indent_for_items
                if first_of_item:
                    # Sibling items in a tight list pack flush together.
                    rendered = replace(
                        cb,
                        body_indent=indent_for_items if not child_is_list else cb.body_indent,
                        marker_runs=marker_runs,
                        marker_x=marker_x,
                        compact=lst.tight and item_idx > 0,
                    )
                    first_of_item = False
                else:
                    # Continuation block within the same item: no marker.
                    rendered = replace(cb, body_indent=item_indent)
                out.append(rendered)

    return out


def _marker_text(lst: List, item_idx: int) -> str:
    """Format the marker string for the item at ``item_idx`` of ``lst``."""
    if lst.ordered:
        return f"{lst.start + item_idx}. "
    return "• "


def _render_paragraph(
    p: Paragraph, family: FontFamily, *, body_size: float = BODY_SIZE,
) -> list[Run]:
    """Turn a Paragraph's inlines into a list of Runs at the body size."""
    runs: list[Run] = []
    for inline in p.inlines:
        runs.extend(_render_inline(inline, family, font=family.regular, size=body_size))
    return runs


def _render_heading(
    h: Heading, family: FontFamily, *, body_size: float = BODY_SIZE,
) -> RenderedBlock:
    """Lower a Heading: bold face at the level-specific size, with spacing.

    The heading size scales off ``body_size`` via _heading_size, so a larger
    body font enlarges headings by the same ratio. The 0.6/0.25 spacing
    factors derive from the resolved heading size and so follow automatically.
    """
    size = _heading_size(h.level, body_size)
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
    strike: bool = False,
) -> list[Run]:
    """Lower one inline node to one or more runs.

    ``font`` is the *current* font (carried through nesting) so that an
    Emphasis inside a Strong picks the family's ``bold_italic`` face
    instead of dropping back to plain italic. ``size`` and ``link_url``
    are carried through nesting — heading inlines stay at heading size,
    and a Strong inside a Link inherits the link annotation. ``strike``
    is set by an enclosing Strikethrough and propagated to every leaf
    Run so the layout can draw a single horizontal bar across them.
    """
    color = LINK_COLOR if link_url is not None else None

    if isinstance(inline, Text):
        # Text may contain emoji, which render as inline images rather than
        # font glyphs. Split into text runs + emoji runs (a no-op returning
        # one plain run when no emoji font is available or none are present).
        return split_text_into_runs(
            inline.content, font=font, size=size,
            link_url=link_url, color=color, strike=strike,
        )

    if isinstance(inline, Code):
        # Code spans are monospace, but emoji are the documented exception
        # to the WinAnsi-`?` rule and must render everywhere — including
        # inside `code`. Route through the splitter so an emoji in a code
        # span becomes an image run (or its fallback label in the font-less
        # tier) instead of leaking a literal `?` from the WinAnsi encoder.
        return split_text_into_runs(
            inline.content, font=family.monospace, size=size,
            link_url=link_url, color=color, strike=strike,
        )

    if isinstance(inline, Strong):
        # Add bold to the current face. If the face already carries italic
        # (a plain italic OR an already-composed bold_italic — the latter
        # happens when a header cell seeds the run as bold and an Emphasis
        # nests a Strong), the result must keep italic → bold_italic. Test
        # the family's italic-bearing faces, not just == italic, so the
        # header seed path composes the same as the body path.
        italic_bearing = font in (family.italic, family.bold_italic)
        next_font = family.bold_italic if italic_bearing else family.bold
        return _flatten(inline.inlines, family, next_font, size, link_url=link_url, strike=strike)

    if isinstance(inline, Emphasis):
        # Add italic to the current face. If the face already carries bold
        # (a plain bold — e.g. a bold header seed — OR an already-composed
        # bold_italic), keep bold → bold_italic.
        bold_bearing = font in (family.bold, family.bold_italic)
        next_font = family.bold_italic if bold_bearing else family.italic
        return _flatten(inline.inlines, family, next_font, size, link_url=link_url, strike=strike)

    if isinstance(inline, Strikethrough):
        return _flatten(inline.inlines, family, font, size, link_url=link_url, strike=True)

    if isinstance(inline, Link):
        # Link children render at the same font/size but with link_url
        # propagated. CommonMark forbids nested links so we don't worry
        # about Link-inside-Link.
        return _flatten(inline.inlines, family, font, size, link_url=inline.url, strike=strike)

    if isinstance(inline, AutoLink):
        return [Run(
            text=inline.text, font=font, size=size,
            link_url=inline.url, color=LINK_COLOR, strike=strike,
        )]

    if isinstance(inline, Image):
        # v0.2 inline fallback: render the alt text in italic in place
        # of the image. Block-level images are intercepted earlier in
        # _render_block; this branch handles mixed-content paragraphs
        # and any image whose source failed to load.
        return _flatten(
            inline.inlines, family, family.italic, size,
            link_url=link_url, strike=strike,
        )

    if isinstance(inline, Subscript):
        # Smaller size, baseline lowered. PDF emitter applies y_shift.
        runs = _flatten(
            inline.inlines, family, font, size * SUBSCRIPT_SIZE_RATIO,
            link_url=link_url, strike=strike,
        )
        return [_with_y_shift(r, -size * SUBSCRIPT_OFFSET_RATIO) for r in runs]

    if isinstance(inline, Superscript):
        runs = _flatten(
            inline.inlines, family, font, size * SUPERSCRIPT_SIZE_RATIO,
            link_url=link_url, strike=strike,
        )
        return [_with_y_shift(r, size * SUPERSCRIPT_OFFSET_RATIO) for r in runs]

    if isinstance(inline, Underline):
        runs = _flatten(
            inline.inlines, family, font, size,
            link_url=link_url, strike=strike,
        )
        return [_with_underline(r) for r in runs]

    if isinstance(inline, Mark):
        runs = _flatten(
            inline.inlines, family, font, size,
            link_url=link_url, strike=strike,
        )
        return [_with_background(r, MARK_FILL) for r in runs]

    if isinstance(inline, Kbd):
        # Monospace + thin border around the run.
        runs = _flatten(
            inline.inlines, family, family.monospace, size,
            link_url=link_url, strike=strike,
        )
        return [_with_border(r, KBD_BORDER) for r in runs]

    if isinstance(inline, HardBreak):
        # Sentinel marker the layout wrapper interprets as a forced
        # line break. The text is the literal byte "\x00" which never
        # appears in user content (the parser maps NUL to U+FFFD per
        # CommonMark normalisation) so the wrapper can recognise it
        # unambiguously.
        return [Run(text="\x00", font=font, size=size)]

    if isinstance(inline, HtmlInline):
        # An HtmlInline that survived to render time means our
        # html_filter didn't promote it — likely an unrecognised stray
        # tag. Drop it (no visible text).
        return []

    raise NotImplementedError(f"render: unsupported inline {type(inline).__name__}")


# Visual constants for the HTML allow-list rendering.
SUBSCRIPT_SIZE_RATIO = 0.75
SUBSCRIPT_OFFSET_RATIO = 0.20    # baseline lowered by 20% of original size
SUPERSCRIPT_SIZE_RATIO = 0.75
SUPERSCRIPT_OFFSET_RATIO = 0.40  # baseline raised by 40% of original size
MARK_FILL = (1.0, 0.95, 0.6)     # pale yellow
KBD_BORDER = (0.5, 0.5, 0.5)     # mid grey


def _with_y_shift(run: Run, shift: float) -> Run:
    """Return a copy of ``run`` with a different baseline shift."""
    from dataclasses import replace
    return replace(run, y_shift=shift)


def _with_underline(run: Run) -> Run:
    from dataclasses import replace
    return replace(run, underline=True)


def _with_background(run: Run, fill: tuple[float, float, float]) -> Run:
    from dataclasses import replace
    return replace(run, background_fill=fill)


def _with_border(run: Run, border: tuple[float, float, float]) -> Run:
    from dataclasses import replace
    return replace(run, border_fill=border)


def _flatten(
    inlines: tuple[Inline, ...],
    family: FontFamily,
    font: str,
    size: float = BODY_SIZE,
    link_url: str | None = None,
    strike: bool = False,
) -> list[Run]:
    """Render a tuple of inline children, carrying font + size + link_url + strike."""
    runs: list[Run] = []
    for inline in inlines:
        runs.extend(_render_inline(
            inline, family, font=font, size=size, link_url=link_url, strike=strike,
        ))
    return runs
