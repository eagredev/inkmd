"""Markdown parser.

CommonMark-subset parser, hand-rolled. Two phases:

1. **Block parse**: split input on blank lines into blocks. v0.0.4
   recognises only paragraphs and blank-line separators — headings,
   lists, code blocks, blockquotes, and tables arrive in 0.0.5+.

2. **Inline parse**: walk each block's text and produce inline AST
   nodes. v0.0.4 produces a single ``Text`` run per paragraph — no
   bold, italic, code spans, or links yet.

This file deliberately stays small for v0.0.4. The shape (parse_inlines
called per block from parse_blocks) is the seam where 0.0.5 will plug
in bold/italic/code recognition without rewriting the block layer.
"""

from __future__ import annotations

from inkmd.ast import Document, Inline, Paragraph, Text


def parse(text: str) -> Document:
    """Parse a markdown string into an AST.

    Public entry point. Normalises line endings (CRLF / CR → LF),
    expands tabs to 4 spaces, then runs the two-phase pipeline.
    """
    normalised = _normalise(text)
    blocks = _parse_blocks(normalised)
    return Document(blocks=tuple(blocks))


def _normalise(text: str) -> str:
    """Normalise line endings and tabs per CommonMark §2.2."""
    # Treat NUL as REPLACEMENT CHARACTER per spec.
    text = text.replace("\x00", "�")
    # CR LF → LF; standalone CR → LF.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Tabs expand to 4 spaces. CommonMark uses tab-stops-of-4 with
    # column-aware expansion, but for v0.0.4 (no indented code blocks)
    # a simple expansion is indistinguishable.
    text = text.expandtabs(4)
    return text


def _parse_blocks(text: str) -> list[Paragraph]:
    """Split ``text`` into paragraphs separated by blank lines."""
    blocks: list[Paragraph] = []
    current_lines: list[str] = []

    def flush() -> None:
        if current_lines:
            joined = " ".join(line.strip() for line in current_lines)
            inlines = _parse_inlines(joined)
            blocks.append(Paragraph(inlines=inlines))
            current_lines.clear()

    for line in text.split("\n"):
        if line.strip() == "":
            flush()
        else:
            current_lines.append(line)
    flush()
    return blocks


def _parse_inlines(text: str) -> tuple[Inline, ...]:
    """Parse a paragraph's text into a tuple of inline nodes.

    v0.0.4: returns a single Text node. The structure stays a tuple so
    0.0.5 can add Strong / Emphasis / Code / Link spans without
    changing the call sites that consume inlines.
    """
    if not text:
        return ()
    return (Text(content=text),)
