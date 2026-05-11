"""Lower a parsed AST into the layout's run-based model.

The seam between markdown semantics (AST) and PDF layout (Run / paginate).
``render_document`` walks blocks, dispatches on type, and yields the
list-of-Run-lists that ``paginate_runs`` expects.

v0.0.4: Paragraph → list[Run] with everything in the family's body
font. The font family is selectable so demo scripts can render samples
in Times (closer match to Nimbus on Linux for visual review) while
the library default stays Helvetica.

0.0.5+ will use the family quadruple's bold / italic / monospace slots
to render Strong, Emphasis, Code, Heading, etc.
"""

from __future__ import annotations

from dataclasses import dataclass

from inkmd.ast import Document, Inline, Paragraph, Text
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


def render_document(doc: Document, family: FontFamily = DEFAULT_FAMILY) -> list[list[Run]]:
    """Lower a Document into the list-of-paragraphs-of-runs that paginate_runs eats."""
    paragraphs: list[list[Run]] = []
    for block in doc.blocks:
        if isinstance(block, Paragraph):
            paragraphs.append(_render_paragraph(block, family))
        else:
            raise NotImplementedError(f"render: unsupported block {type(block).__name__}")
    return paragraphs


def _render_paragraph(p: Paragraph, family: FontFamily) -> list[Run]:
    """Turn a Paragraph's inlines into a list of Runs."""
    runs: list[Run] = []
    for inline in p.inlines:
        runs.extend(_render_inline(inline, family))
    return runs


def _render_inline(inline: Inline, family: FontFamily) -> list[Run]:
    """Lower one inline node to one or more runs."""
    if isinstance(inline, Text):
        return [Run(text=inline.content, font=family.regular, size=BODY_SIZE)]
    raise NotImplementedError(f"render: unsupported inline {type(inline).__name__}")
