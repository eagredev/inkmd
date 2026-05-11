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
    """
    text: str
    font: str
    size: float


@dataclass(frozen=True)
class PositionedRun:
    """A run with its absolute (x, y) baseline position on the page."""
    text: str
    x: float
    y: float
    font: str
    size: float


@dataclass(frozen=True)
class StyledLine:
    """A line composed of one or more runs sharing the same baseline."""
    runs: tuple[PositionedRun, ...]


@dataclass(frozen=True)
class Page:
    """A list of lines that share one physical page.

    For the single-font path this holds ``Line`` records; for the styled
    path it holds ``StyledLine`` records. The two are kept separate so
    the existing PDF emission can branch on type.
    """
    lines: tuple
    width: float
    height: float


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
        # delimiter via a manual loop.
        i = 0
        text = run.text
        while i < len(text):
            j = i
            if text[i].isspace():
                while j < len(text) and text[j].isspace():
                    j += 1
                out.append(Run(text=" ", font=run.font, size=run.size))
            else:
                while j < len(text) and not text[j].isspace():
                    j += 1
                out.append(Run(text=text[i:j], font=run.font, size=run.size))
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


def _block_parts(block) -> _BlockParts:
    """Normalise a paginator input element.

    Accepts a bare ``list[Run]`` (treated as a plain paragraph with no
    extra spacing or indent) or any object exposing the relevant
    attributes (e.g. ``render.RenderedBlock``). The layout module
    deliberately does not import render to keep the layer order clean.
    """
    if hasattr(block, "runs"):
        return _BlockParts(
            runs=list(block.runs),
            space_above=float(getattr(block, "space_above", 0.0)),
            space_below=float(getattr(block, "space_below", 0.0)),
            body_indent=float(getattr(block, "body_indent", 0.0)),
            marker_runs=tuple(getattr(block, "marker_runs", ())),
            marker_x=float(getattr(block, "marker_x", 0.0)),
            compact=bool(getattr(block, "compact", False)),
        )
    return _BlockParts(
        runs=list(block),
        space_above=0.0,
        space_below=0.0,
        body_indent=0.0,
        marker_runs=(),
        marker_x=0.0,
        compact=False,
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
    y_cursor = top_y

    def flush_page() -> None:
        if current_lines:
            pages.append(Page(tuple(current_lines), page_width, page_height))

    for p_idx, raw_block in enumerate(paragraphs):
        parts = _block_parts(raw_block)
        if p_idx > 0 and parts.space_above and current_lines:
            y_cursor -= parts.space_above
        # Body column is narrower when this block is indented.
        body_column_width = column_width - parts.body_indent
        wrapped = wrap_runs(parts.runs, body_column_width) if parts.runs else [[]]
        first_line = True
        for line in wrapped:
            line_height = line_height_ratio * (
                _line_max_size(line) if line else DEFAULT_FONT_SIZE
            )
            y_cursor -= line_height
            if y_cursor < bottom_y:
                flush_page()
                current_lines = []
                y_cursor = top_y - line_height
            x = margin + parts.body_indent
            positioned: list[PositionedRun] = []
            # On the first wrapped line, render the marker (if any) at marker_x.
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
                    )
                )
                x += text_width(run.text, run.font, run.size)
            current_lines.append(StyledLine(tuple(positioned)))
            first_line = False
        if p_idx < len(paragraphs) - 1:
            # The default paragraph_spacing applies unless the *next* block
            # asked to be compact (set on next iteration via space_above
            # check). For simplicity, always add paragraph_spacing + this
            # block's space_below; the next block's space_above (which may
            # be negative for compact lists) corrects it.
            y_cursor -= parts.space_below
            # Look at next block for compactness.
            next_parts = _block_parts(paragraphs[p_idx + 1])
            if not next_parts.compact:
                y_cursor -= paragraph_spacing

    flush_page()
    return pages
