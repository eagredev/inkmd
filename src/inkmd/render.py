"""Lower a parsed AST into the layout's run-based model.

The seam between markdown semantics (AST) and PDF layout (Run / paginate).
``render_document`` walks blocks, dispatches on type, and yields the
list-of-Run-lists that ``paginate_runs`` expects.

v0.0.4: Paragraph → list[Run] with everything in body font. 0.0.5+
adds Heading (larger size + bold), List (indent + bullet), Strong
(bold font slot), Emphasis (oblique), Code (Courier), etc.
"""

from __future__ import annotations

from inkmd.ast import Document, Inline, Paragraph, Text
from inkmd.layout import Run


BODY_FONT = "Helvetica"
BODY_SIZE = 12.0


def render_document(doc: Document) -> list[list[Run]]:
    """Lower a Document into the list-of-paragraphs-of-runs that paginate_runs eats."""
    paragraphs: list[list[Run]] = []
    for block in doc.blocks:
        if isinstance(block, Paragraph):
            paragraphs.append(_render_paragraph(block))
        else:
            # Future block types route through here. Unknown nodes are
            # a programming error, not user error — fail loudly so the
            # bug shows up close to where it was introduced.
            raise NotImplementedError(f"render: unsupported block {type(block).__name__}")
    return paragraphs


def _render_paragraph(p: Paragraph) -> list[Run]:
    """Turn a Paragraph's inlines into a list of Runs."""
    runs: list[Run] = []
    for inline in p.inlines:
        runs.extend(_render_inline(inline))
    return runs


def _render_inline(inline: Inline) -> list[Run]:
    """Lower one inline node to one or more runs."""
    if isinstance(inline, Text):
        return [Run(text=inline.content, font=BODY_FONT, size=BODY_SIZE)]
    raise NotImplementedError(f"render: unsupported inline {type(inline).__name__}")
