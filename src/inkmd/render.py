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
    Code,
    Document,
    Emphasis,
    Heading,
    Inline,
    List,
    ListItem,
    Paragraph,
    Strong,
    Text,
)
from inkmd.layout import Run


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


# Layout constants for lists. ``LIST_INDENT_PT`` is the horizontal step per
# nesting level — wide enough that the marker has room to sit visibly to
# the left of the body. The bullet marker is "•" (U+2022); WinAnsi maps it
# at byte 0x95.
LIST_INDENT_PT = 18.0
TIGHT_ITEM_SPACING = 0.0
LOOSE_ITEM_SPACING = 4.0
LIST_BLOCK_SPACE_ABOVE = 3.0
LIST_BLOCK_SPACE_BELOW = 3.0


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
    raise NotImplementedError(f"render: unsupported block {type(block).__name__}")


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
    inline: Inline, family: FontFamily, font: str, size: float = BODY_SIZE
) -> list[Run]:
    """Lower one inline node to one or more runs.

    ``font`` is the *current* font (carried through nesting) so that an
    Emphasis inside a Strong picks the family's ``bold_italic`` face
    instead of dropping back to plain italic. ``size`` is carried
    through nesting too — heading inlines stay at heading size when
    they contain Strong/Emphasis.
    """
    if isinstance(inline, Text):
        return [Run(text=inline.content, font=font, size=size)]

    if isinstance(inline, Code):
        return [Run(text=inline.content, font=family.monospace, size=size)]

    if isinstance(inline, Strong):
        next_font = (
            family.bold_italic if font == family.italic else family.bold
        )
        return _flatten(inline.inlines, family, next_font, size)

    if isinstance(inline, Emphasis):
        next_font = (
            family.bold_italic if font == family.bold else family.italic
        )
        return _flatten(inline.inlines, family, next_font, size)

    raise NotImplementedError(f"render: unsupported inline {type(inline).__name__}")


def _flatten(
    inlines: tuple[Inline, ...], family: FontFamily, font: str, size: float = BODY_SIZE
) -> list[Run]:
    """Render a tuple of inline children, carrying font + size through."""
    runs: list[Run] = []
    for inline in inlines:
        runs.extend(_render_inline(inline, family, font=font, size=size))
    return runs
