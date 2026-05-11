"""Greedy line-wrapping + page pagination.

Milestone 0.0.2: text-only layout. No headings, no font switches, no
images — those arrive in later milestones. The job here is to turn
a stream of paragraphs into a list of pages, each page being a list
of lines that fit within the column width.

Strategy:
  1. Split each paragraph into words on whitespace.
  2. Greedily fill lines: add a word if it fits, otherwise break.
  3. Words longer than the column overflow into their own line (no
     hyphenation in v0.1).
  4. Lines accumulate onto a page until y_cursor crosses the bottom
     margin; then start a new page.

Coordinate system is PDF-native: origin bottom-left, y increases up.
The caller works in terms of margins (top/bottom/left), and we
convert internally.
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
    """A single line of text positioned on a page (in PDF coords)."""
    text: str
    x: float
    y: float
    font: str
    size: float


@dataclass(frozen=True)
class Page:
    """A list of lines that share one physical page."""
    lines: tuple[Line, ...]
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
