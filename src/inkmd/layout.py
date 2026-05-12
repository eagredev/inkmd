"""Greedy line-wrapping + page pagination.

Milestone 0.0.2 introduced single-font wrapping and pagination on plain
strings. Milestone 0.0.3 adds styled runs: a paragraph is now a list of
``Run`` records, each tagged with its own font and size, and a line is
a list of positioned runs. The single-font path remains for backward
compatibility (used by ``text_pdf``).

Strategy is unchanged:
  1. Split paragraphs into atomic units on whitespace.
  2. Greedily fill lines: add a unit if it fits, otherwise break.
  3. Single units wider than the column overflow into their own line.
  4. Lines accumulate onto a page until y_cursor crosses the bottom
     margin; then start a new page.

Coordinate system is PDF-native: origin bottom-left, y increases up.
"""

from __future__ import annotations

from dataclasses import dataclass

from inkmd.fonts import text_width


# Default layout constants — fine-tuned in later milestones.
DEFAULT_FONT = "Helvetica"
DEFAULT_FONT_SIZE = 12.0
DEFAULT_LINE_HEIGHT = 14.4  # 1.2x font size — typical reading leading
DEFAULT_MARGIN = 72.0  # 1 inch on all sides


@dataclass(frozen=True)
class Line:
    """A single line of text positioned on a page (in PDF coords).

    Used by the single-font path. The styled path uses ``StyledLine``.
    """
    text: str
    x: float
    y: float
    font: str
    size: float


@dataclass(frozen=True)
class Run:
    """A fragment of inline text with a single font/size.

    Runs are the atomic unit of styled text. ``text`` is the literal
    string; whitespace inside it is preserved (used for the space chars
    that join wrapped lines).

    ``link_url`` is set for runs that are part of an ``[text](url)`` /
    ``<url>`` link; the layout collects per-line link extents and the
    PDF layer emits clickable annotations + a blue underline.

    ``strike`` is True for runs inside ``~~text~~`` GFM strikethrough;
    the layout collects per-line strike extents and emits a thin
    horizontal rectangle through the glyph mid-height.
    """
    text: str
    font: str
    size: float
    link_url: str | None = None
    color: tuple[float, float, float] | None = None  # None means default (black)
    strike: bool = False


@dataclass(frozen=True)
class PositionedRun:
    """A run with its absolute (x, y) baseline position on the page."""
    text: str
    x: float
    y: float
    font: str
    size: float
    link_url: str | None = None
    color: tuple[float, float, float] | None = None
    strike: bool = False


@dataclass(frozen=True)
class StyledLine:
    """A line composed of one or more runs sharing the same baseline."""
    runs: tuple[PositionedRun, ...]


@dataclass(frozen=True)
class Rect:
    """An axis-aligned filled rectangle on a page.

    PDF-coordinate (origin bottom-left). ``fill`` is RGB in 0..1 floats.
    Drawn *before* lines so text overlays it cleanly.
    """
    x: float
    y: float
    width: float
    height: float
    fill: tuple[float, float, float]


@dataclass(frozen=True)
class LinkAnnotation:
    """A clickable link region on a page (PDF Annot of subtype /Link).

    ``url`` is the destination; ``x``, ``y``, ``width``, ``height`` are
    the clickable bounding box in PDF coordinates. One link that wraps
    across multiple lines produces multiple annotations (one per line).
    """
    url: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class Page:
    """A list of lines that share one physical page.

    For the single-font path this holds ``Line`` records; for the styled
    path it holds ``StyledLine`` records. ``shapes`` are filled background
    rectangles drawn before the lines. ``annotations`` are clickable link
    regions emitted as PDF /Link annotations.
    """
    lines: tuple
    width: float
    height: float
    shapes: tuple = ()
    annotations: tuple = ()


def wrap_paragraph(
    text: str,
    column_width: float,
    font: str = DEFAULT_FONT,
    size: float = DEFAULT_FONT_SIZE,
) -> list[str]:
    """Greedy-wrap one paragraph to fit ``column_width`` points.

    Words are taken to be whitespace-separated runs. Single words wider
    than the column get their own line (no hyphenation); the resulting
    line will overflow visually but we don't attempt to shrink or break
    the word in v0.1.
    """
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    space_w = text_width(" ", font, size)

    for word in words[1:]:
        candidate_w = (
            text_width(current, font, size)
            + space_w
            + text_width(word, font, size)
        )
        if candidate_w <= column_width:
            current = current + " " + word
        else:
            lines.append(current)
            current = word

    lines.append(current)
    return lines


def paginate(
    paragraphs: list[str],
    page_width: float,
    page_height: float,
    margin: float = DEFAULT_MARGIN,
    font: str = DEFAULT_FONT,
    size: float = DEFAULT_FONT_SIZE,
    line_height: float = DEFAULT_LINE_HEIGHT,
    paragraph_spacing: float = 6.0,
) -> list[Page]:
    """Wrap and paginate ``paragraphs`` into one or more ``Page`` objects.

    ``margin`` applies symmetrically to all four sides. ``line_height``
    is the baseline-to-baseline distance. ``paragraph_spacing`` is
    additional gap between consecutive paragraphs.
    """
    column_width = page_width - 2 * margin
    top_y = page_height - margin
    bottom_y = margin

    pages: list[Page] = []
    current_lines: list[Line] = []
    y_cursor = top_y

    def flush_page() -> None:
        if current_lines:
            pages.append(Page(tuple(current_lines), page_width, page_height))

    for p_idx, para in enumerate(paragraphs):
        wrapped = wrap_paragraph(para, column_width, font, size)
        for w_idx, line_text in enumerate(wrapped):
            # Reserve vertical space for one line; the *baseline* sits
            # ``line_height`` below the previous baseline (or below the
            # top margin for the first line on a page).
            y_cursor -= line_height
            if y_cursor < bottom_y:
                flush_page()
                current_lines = []
                y_cursor = top_y - line_height
            current_lines.append(
                Line(text=line_text, x=margin, y=y_cursor, font=font, size=size)
            )
        # Inter-paragraph spacing (not applied after the last paragraph).
        if p_idx < len(paragraphs) - 1:
            y_cursor -= paragraph_spacing

    flush_page()
    return pages


def split_paragraphs(text: str) -> list[str]:
    """Split a plaintext blob into paragraphs on blank lines.

    Empty paragraphs are dropped. Internal newlines within a paragraph
    are flattened to spaces (we'll respect hard line breaks once
    markdown parsing lands).
    """
    raw_blocks = text.split("\n\n")
    paragraphs = []
    for block in raw_blocks:
        flattened = " ".join(block.split())
        if flattened:
            paragraphs.append(flattened)
    return paragraphs


# --- Styled-text path -----------------------------------------------------


def _runs_width(runs: list[Run]) -> float:
    """Sum the rendered width of a list of runs."""
    return sum(text_width(r.text, r.font, r.size) for r in runs)


def _tokenise_runs(runs: list[Run]) -> list[Run]:
    """Split each run on whitespace so wrapping has atomic units.

    The whitespace itself becomes its own run with the *previous* run's
    style, so that a leading space between two styled fragments inherits
    sensible formatting. Empty resulting fragments are dropped.
    """
    out: list[Run] = []
    for run in runs:
        if not run.text:
            continue
        # Preserve internal whitespace as separate tokens so we can break
        # on it later. We split on any run of whitespace, keeping the
        # delimiter via a manual loop. The whitespace token inherits
        # link_url so an interior space inside a link still has the
        # underline + annotation.
        i = 0
        text = run.text
        while i < len(text):
            j = i
            if text[i].isspace():
                while j < len(text) and text[j].isspace():
                    j += 1
                out.append(Run(
                    text=" ", font=run.font, size=run.size,
                    link_url=run.link_url, color=run.color, strike=run.strike,
                ))
            else:
                while j < len(text) and not text[j].isspace():
                    j += 1
                out.append(Run(
                    text=text[i:j], font=run.font, size=run.size,
                    link_url=run.link_url, color=run.color, strike=run.strike,
                ))
            i = j
    return out


def wrap_runs(
    runs: list[Run],
    column_width: float,
) -> list[list[Run]]:
    """Greedy-wrap a list of runs into lines that fit ``column_width``.

    Each returned line is a list of runs; concatenating their texts
    gives the line's visible string. Leading and trailing whitespace
    runs on each wrapped line are stripped.
    """
    tokens = _tokenise_runs(runs)
    if not tokens:
        return []

    lines: list[list[Run]] = []
    current: list[Run] = []
    current_width = 0.0

    def is_space(tok: Run) -> bool:
        return tok.text == " "

    def strip_edges(line: list[Run]) -> list[Run]:
        while line and is_space(line[0]):
            line.pop(0)
        while line and is_space(line[-1]):
            line.pop()
        return line

    for tok in tokens:
        tok_w = text_width(tok.text, tok.font, tok.size)
        # If the very next token is a space and current line is empty,
        # skip it — don't start a wrapped line with leading whitespace.
        if not current and is_space(tok):
            continue
        if current_width + tok_w <= column_width or not current:
            current.append(tok)
            current_width += tok_w
        else:
            lines.append(strip_edges(current))
            # If the token that triggered the break is itself a space,
            # consume it instead of starting the next line with a space.
            if is_space(tok):
                current = []
                current_width = 0.0
            else:
                current = [tok]
                current_width = tok_w

    if current:
        lines.append(strip_edges(current))
    return [ln for ln in lines if ln]


def _line_max_size(line: list[Run]) -> float:
    """Largest font size on a line, used to set the line's leading."""
    return max((r.size for r in line), default=DEFAULT_FONT_SIZE)


@dataclass(frozen=True)
class _BlockParts:
    """Normalised paginator input: runs, spacing, indent, optional marker."""
    runs: list[Run]
    space_above: float
    space_below: float
    body_indent: float
    marker_runs: tuple[Run, ...]
    marker_x: float
    compact: bool  # if True, suppress the default paragraph_spacing gap before this block
    left_rules: tuple[float, ...]
    left_rule_fill: tuple[float, float, float]
    background_fill: tuple[float, float, float] | None
    bg_padding: float
    preserve_lines: bool
    prepositioned: bool
    prepositioned_lines: tuple
    prepositioned_line_heights: tuple
    prepositioned_shapes: tuple


def _block_parts(block) -> _BlockParts:
    """Normalise a paginator input element.

    Accepts a bare ``list[Run]`` (treated as a plain paragraph with no
    extra spacing or indent) or any object exposing the relevant
    attributes (e.g. ``render.RenderedBlock``). The layout module
    deliberately does not import render to keep the layer order clean.
    """
    if hasattr(block, "runs"):
        bg = getattr(block, "background_fill", None)
        rules = getattr(block, "left_rules", ())
        return _BlockParts(
            runs=list(block.runs),
            space_above=float(getattr(block, "space_above", 0.0)),
            space_below=float(getattr(block, "space_below", 0.0)),
            body_indent=float(getattr(block, "body_indent", 0.0)),
            marker_runs=tuple(getattr(block, "marker_runs", ())),
            marker_x=float(getattr(block, "marker_x", 0.0)),
            compact=bool(getattr(block, "compact", False)),
            left_rules=tuple(float(r) for r in rules),
            left_rule_fill=tuple(getattr(block, "left_rule_fill", (0.6, 0.6, 0.6))),
            background_fill=tuple(bg) if bg is not None else None,
            bg_padding=float(getattr(block, "bg_padding", 4.0)),
            preserve_lines=bool(getattr(block, "preserve_lines", False)),
            prepositioned=bool(getattr(block, "prepositioned", False)),
            prepositioned_lines=tuple(getattr(block, "prepositioned_lines", ())),
            prepositioned_line_heights=tuple(getattr(block, "prepositioned_line_heights", ())),
            prepositioned_shapes=tuple(getattr(block, "prepositioned_shapes", ())),
        )
    return _BlockParts(
        runs=list(block),
        space_above=0.0,
        space_below=0.0,
        body_indent=0.0,
        marker_runs=(),
        marker_x=0.0,
        compact=False,
        left_rules=(),
        left_rule_fill=(0.6, 0.6, 0.6),
        background_fill=None,
        bg_padding=4.0,
        preserve_lines=False,
        prepositioned=False,
        prepositioned_lines=(),
        prepositioned_line_heights=(),
        prepositioned_shapes=(),
    )


def paginate_runs(
    paragraphs,
    page_width: float,
    page_height: float,
    margin: float = DEFAULT_MARGIN,
    line_height_ratio: float = 1.2,
    paragraph_spacing: float = 6.0,
) -> list[Page]:
    """Wrap and paginate styled blocks into ``Page`` records.

    Each element of ``paragraphs`` is either a bare ``list[Run]`` (plain
    paragraph) or a ``RenderedBlock``-like carrier with optional
    ``space_above`` / ``space_below`` hints (additive to the default
    inter-block spacing). Line height is set per-line as
    ``line_height_ratio * max font size on the line``. Page breaks fire
    when the next line's baseline would fall below the bottom margin;
    space-above before a block is suppressed at the top of a fresh page.
    """
    column_width = page_width - 2 * margin
    top_y = page_height - margin
    bottom_y = margin

    pages: list[Page] = []
    current_lines: list[StyledLine] = []
    current_shapes: list[Rect] = []
    current_annotations: list[LinkAnnotation] = []
    y_cursor = top_y

    def flush_page() -> None:
        if current_lines:
            pages.append(
                Page(
                    tuple(current_lines),
                    page_width,
                    page_height,
                    shapes=tuple(current_shapes),
                    annotations=tuple(current_annotations),
                )
            )

    for p_idx, raw_block in enumerate(paragraphs):
        parts = _block_parts(raw_block)
        if p_idx > 0 and parts.space_above and current_lines:
            y_cursor -= parts.space_above

        # Prepositioned content (tables): atomic placement, translate
        # relative coordinates to absolute.
        if parts.prepositioned:
            # Compute the table's total height from the deepest line / shape.
            total_h = 0.0
            for shape_dict in parts.prepositioned_shapes:
                bottom = shape_dict["rel_y_top"] + shape_dict["height"]
                if bottom > total_h:
                    total_h = bottom
            for line_record in parts.prepositioned_lines:
                _baseline_from_top, _runs = line_record
                if _baseline_from_top > total_h:
                    total_h = _baseline_from_top
            # If the table doesn't fit on the current page, flush and start fresh.
            if y_cursor - total_h < bottom_y and current_lines:
                flush_page()
                current_lines = []
                current_shapes = []
                current_annotations = []
                y_cursor = top_y
            table_top_y = y_cursor
            # Translate every relative shape to absolute Rect.
            for shape_dict in parts.prepositioned_shapes:
                rect = Rect(
                    x=margin + shape_dict["x_offset"],
                    y=table_top_y - shape_dict["rel_y_top"] - shape_dict["height"],
                    width=shape_dict["width"],
                    height=shape_dict["height"],
                    fill=shape_dict["fill"],
                )
                current_shapes.append(rect)
            # Translate every relative positioned-run line.
            for baseline_from_top, runs_record in parts.prepositioned_lines:
                positioned_list = []
                for pr in runs_record:
                    positioned_list.append(
                        PositionedRun(
                            text=pr.text,
                            x=margin + pr.x_rel,
                            y=table_top_y - pr.y_from_top,
                            font=pr.font,
                            size=pr.size,
                            link_url=getattr(pr, "link_url", None),
                            color=getattr(pr, "color", None),
                            strike=getattr(pr, "strike", False),
                        )
                    )
                current_lines.append(StyledLine(tuple(positioned_list)))
                # Link decorations within table cells.
                for ul_rect, ann in _link_decorations(positioned_list):
                    current_shapes.append(ul_rect)
                    current_annotations.append(ann)
                # Strikethrough decorations within table cells.
                for sk_rect in _strike_decorations(positioned_list):
                    current_shapes.append(sk_rect)
            y_cursor = table_top_y - total_h
            if p_idx < len(paragraphs) - 1:
                y_cursor -= parts.space_below
                next_parts = _block_parts(paragraphs[p_idx + 1])
                if not next_parts.compact:
                    y_cursor -= paragraph_spacing
            continue

        body_column_width = column_width - parts.body_indent

        if parts.preserve_lines:
            # Code-block wrap column: left is body_indent (already in
            # body_column_width); also reserve bg_padding of right
            # padding so the rightmost glyph doesn't crash into the
            # background fill edge.
            code_column = body_column_width - parts.bg_padding
            wrapped = _split_preserved_lines(parts.runs, code_column)
        else:
            wrapped = wrap_runs(parts.runs, body_column_width) if parts.runs else [[]]

        first_line = True
        # Track per-page top/bottom for background fill that spans the block.
        block_top_on_page: float | None = None
        block_bottom_on_page: float | None = None

        def emit_bg_rect() -> None:
            nonlocal current_shapes
            if (
                parts.background_fill is not None
                and block_top_on_page is not None
                and block_bottom_on_page is not None
            ):
                x_start = margin
                width = column_width
                top = block_top_on_page + parts.bg_padding
                bottom = block_bottom_on_page - parts.bg_padding
                current_shapes.append(
                    Rect(
                        x=x_start,
                        y=bottom,
                        width=width,
                        height=top - bottom,
                        fill=parts.background_fill,
                    )
                )

        for line in wrapped:
            line_height = line_height_ratio * (
                _line_max_size(line) if line else DEFAULT_FONT_SIZE
            )
            # Tentatively place baseline at y_cursor - line_height.
            new_y = y_cursor - line_height
            if new_y < bottom_y:
                # Emit pending background for the just-completed page region.
                emit_bg_rect()
                block_top_on_page = None
                block_bottom_on_page = None
                flush_page()
                current_lines = []
                current_shapes = []
                current_annotations = []
                y_cursor = top_y
                new_y = y_cursor - line_height
            y_cursor = new_y

            if block_top_on_page is None:
                block_top_on_page = y_cursor + line_height  # top of this line
            block_bottom_on_page = y_cursor  # baseline; bottom-padding accounts for descender

            x = margin + parts.body_indent
            positioned: list[PositionedRun] = []
            if first_line and parts.marker_runs:
                mx = margin + parts.marker_x
                for mrun in parts.marker_runs:
                    positioned.append(
                        PositionedRun(
                            text=mrun.text,
                            x=mx,
                            y=y_cursor,
                            font=mrun.font,
                            size=mrun.size,
                        )
                    )
                    mx += text_width(mrun.text, mrun.font, mrun.size)
            for run in line:
                positioned.append(
                    PositionedRun(
                        text=run.text,
                        x=x,
                        y=y_cursor,
                        font=run.font,
                        size=run.size,
                        link_url=run.link_url,
                        color=run.color,
                        strike=run.strike,
                    )
                )
                x += text_width(run.text, run.font, run.size)
            current_lines.append(StyledLine(tuple(positioned)))
            # Collect link annotations + underline shapes for this line.
            for ul_rect, ann in _link_decorations(positioned):
                current_shapes.append(ul_rect)
                current_annotations.append(ann)
            # Collect strikethrough shapes for this line.
            for sk_rect in _strike_decorations(positioned):
                current_shapes.append(sk_rect)
            # Per-line left rules for blockquotes. Multiple rules =
            # nested quote depth, each at its own x offset.
            for rule_x_rel in parts.left_rules:
                rule_w = 2.0
                rule_x = margin + rule_x_rel
                current_shapes.append(
                    Rect(
                        x=rule_x,
                        y=y_cursor - 2.0,
                        width=rule_w,
                        height=line_height,
                        fill=parts.left_rule_fill,
                    )
                )
            first_line = False

        # Emit background fill for this block on this page.
        emit_bg_rect()

        if p_idx < len(paragraphs) - 1:
            y_cursor -= parts.space_below
            next_parts = _block_parts(paragraphs[p_idx + 1])
            if not next_parts.compact:
                y_cursor -= paragraph_spacing

    flush_page()
    return pages


def _link_decorations(
    positioned: list[PositionedRun],
) -> list[tuple[Rect, LinkAnnotation]]:
    """Group adjacent same-URL runs on one line into ``(underline, annot)`` pairs.

    Each contiguous run of same-URL runs yields:
      - A thin filled rectangle below the baseline (the visible underline).
      - A LinkAnnotation covering the full text extent + a couple of
        points of vertical padding (the clickable area).

    Non-adjacent same-URL runs (e.g. ``[a](u) [b](u)``) become separate
    pairs — that's the correct behaviour for two distinct links that
    happen to share a URL.
    """
    out: list[tuple[Rect, LinkAnnotation]] = []
    i = 0
    n = len(positioned)
    while i < n:
        run = positioned[i]
        if run.link_url is None:
            i += 1
            continue
        url = run.link_url
        start_x = run.x
        last_run = run
        j = i + 1
        while j < n and positioned[j].link_url == url:
            last_run = positioned[j]
            j += 1
        end_x = last_run.x + text_width(last_run.text, last_run.font, last_run.size)
        baseline_y = run.y
        size = run.size
        underline_thickness = max(0.5, size * 0.05)
        underline_offset = size * 0.12  # below baseline
        ul = Rect(
            x=start_x,
            y=baseline_y - underline_offset - underline_thickness,
            width=end_x - start_x,
            height=underline_thickness,
            fill=run.color or (0.0, 0.0, 0.0),
        )
        # Annotation rect: a bit taller than the underline, encompassing
        # the glyph height. PDF readers usually highlight on hover.
        ann_h = size * 1.1
        ann_y = baseline_y - underline_offset - underline_thickness
        ann = LinkAnnotation(
            url=url,
            x=start_x,
            y=ann_y,
            width=end_x - start_x,
            height=ann_h,
        )
        out.append((ul, ann))
        i = j
    return out


def _strike_decorations(positioned: list[PositionedRun]) -> list[Rect]:
    """Group adjacent strike runs on one line into horizontal-bar rectangles.

    Each contiguous run of struck runs yields one thin filled rectangle
    crossing the glyph mid-height. Non-adjacent struck runs (separated
    by a non-struck run) become separate bars.
    """
    out: list[Rect] = []
    i = 0
    n = len(positioned)
    while i < n:
        run = positioned[i]
        if not run.strike:
            i += 1
            continue
        start_x = run.x
        last_run = run
        j = i + 1
        while j < n and positioned[j].strike:
            last_run = positioned[j]
            j += 1
        end_x = last_run.x + text_width(last_run.text, last_run.font, last_run.size)
        size = run.size
        thickness = max(0.5, size * 0.06)
        # Strike sits roughly at the visual x-height midline (~36% above
        # baseline for the body fonts we ship).
        offset = size * 0.30
        out.append(
            Rect(
                x=start_x,
                y=run.y + offset,
                width=end_x - start_x,
                height=thickness,
                fill=run.color or (0.0, 0.0, 0.0),
            )
        )
        i = j
    return out


def _split_preserved_lines(
    runs: list[Run], column_width: float | None = None
) -> list[list[Run]]:
    """Split runs on embedded ``\\n`` for code blocks, then soft-wrap.

    Each source line (delimited by ``\\n``) is preserved as a logical
    unit so whitespace within it stays intact. If ``column_width`` is
    set and a source line's rendered width exceeds it, the line is
    soft-wrapped at the last whitespace before the overflow point;
    if no whitespace exists, the line is hard-broken at the column
    boundary. Continuation lines are flat (no indent change) so they
    align with the original line's left edge under the same body_indent.
    """
    source_lines: list[list[Run]] = []
    current: list[Run] = []
    for run in runs:
        parts = run.text.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                source_lines.append(current)
                current = []
            if part:
                current.append(Run(text=part, font=run.font, size=run.size))
    source_lines.append(current)

    if column_width is None:
        return source_lines

    wrapped: list[list[Run]] = []
    for line in source_lines:
        wrapped.extend(_wrap_preserved_line(line, column_width))
    return wrapped


def _wrap_preserved_line(line: list[Run], column_width: float) -> list[list[Run]]:
    """Wrap a single preserved-whitespace line at the column boundary.

    Walks the line char-by-char, tracking accumulated width. When width
    exceeds column_width, break at the last whitespace seen if any;
    otherwise hard-break at the current position. Continues until the
    whole line is consumed.
    """
    if not line:
        return [[]]
    # Fast path: does the whole line already fit?
    total = sum(text_width(r.text, r.font, r.size) for r in line)
    if total <= column_width:
        return [line]

    # Flatten the line into (char, font, size) tuples so we can walk
    # codepoint-by-codepoint while tracking width and run boundaries.
    chars: list[tuple[str, str, float]] = []
    for r in line:
        for ch in r.text:
            chars.append((ch, r.font, r.size))

    def make_runs(start: int, end: int) -> list[Run]:
        out: list[Run] = []
        buf = ""
        cur_font = chars[start][1]
        cur_size = chars[start][2]
        for ch, font, size in chars[start:end]:
            if font != cur_font or size != cur_size:
                if buf:
                    out.append(Run(text=buf, font=cur_font, size=cur_size))
                buf = ch
                cur_font = font
                cur_size = size
            else:
                buf += ch
        if buf:
            out.append(Run(text=buf, font=cur_font, size=cur_size))
        return out

    wrapped: list[list[Run]] = []
    start = 0
    i = 0
    last_space = -1
    width_so_far = 0.0
    while i < len(chars):
        ch, font, size = chars[i]
        w = text_width(ch, font, size)
        if width_so_far + w > column_width and i > start:
            # Break point: prefer last_space if found within this segment.
            if last_space > start:
                wrapped.append(make_runs(start, last_space))
                start = last_space + 1  # skip the whitespace itself
            else:
                # Hard break — no whitespace available.
                wrapped.append(make_runs(start, i))
                start = i
            i = start
            last_space = -1
            width_so_far = 0.0
            continue
        if ch == " ":
            last_space = i
        width_so_far += w
        i += 1
    if start < len(chars):
        wrapped.append(make_runs(start, len(chars)))
    return wrapped or [[]]
