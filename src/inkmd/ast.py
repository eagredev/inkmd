"""Markdown AST node types.

Two layers: block-level (Paragraph, Heading, List, CodeBlock, BlankLine, …)
and inline-level (Text, Strong, Emphasis, Code, Link). v0.0.5 ships
Document, Paragraph, Text, Strong, Emphasis, and Code. Headings, lists,
blockquotes, links, and images land in 0.0.6+.

Why dataclasses + tuples (not lists, not classes): immutable frozen
dataclasses make the AST hashable, comparable, and safely shareable
across pipeline stages. Tuples instead of lists for the same reason.
The parser builds and returns; nothing mutates downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


# --- Inline nodes ---------------------------------------------------------


@dataclass(frozen=True)
class Text:
    """Plain text content within a block."""
    content: str


@dataclass(frozen=True)
class Strong:
    """**Bold** emphasis. Contains inline children."""
    inlines: tuple["Inline", ...]


@dataclass(frozen=True)
class Emphasis:
    """*Italic* emphasis. Contains inline children."""
    inlines: tuple["Inline", ...]


@dataclass(frozen=True)
class Code:
    """``Inline code`` — opaque content, no nested parsing."""
    content: str


@dataclass(frozen=True)
class Link:
    """``[text](url)`` style link with optional title.

    The link text ``inlines`` may itself contain Strong/Emphasis/Code
    (but not nested Link per CommonMark). ``url`` is the destination;
    ``title`` is the optional tooltip-style string from ``[text](url "title")``.
    """
    inlines: tuple["Inline", ...]
    url: str
    title: str = ""


@dataclass(frozen=True)
class AutoLink:
    """``<https://example.com>`` style autolink — URL is both target and display."""
    url: str


Inline = Union[Text, Strong, Emphasis, Code, Link, AutoLink]


# --- Block nodes ----------------------------------------------------------


@dataclass(frozen=True)
class Paragraph:
    """A block of flowing text composed of inline nodes."""
    inlines: tuple[Inline, ...]


@dataclass(frozen=True)
class Heading:
    """An ATX or Setext heading. ``level`` is 1..6."""
    level: int
    inlines: tuple[Inline, ...]


@dataclass(frozen=True)
class ListItem:
    """One item in a list; holds a sequence of child blocks.

    Items can contain paragraphs, nested lists, or other block types.
    Tight-list items typically hold a single Paragraph; loose-list items
    may hold multiple blocks.
    """
    blocks: tuple["Block", ...]


@dataclass(frozen=True)
class List:
    """An ordered or unordered list.

    ``ordered`` is True for ``1. foo`` style; False for ``- foo``.
    ``start`` is the starting number for ordered lists (1 if unset).
    ``tight`` controls vertical spacing — set during block parse based
    on whether items are blank-separated.
    """
    ordered: bool
    start: int
    tight: bool
    items: tuple[ListItem, ...]


@dataclass(frozen=True)
class BlockQuote:
    """A blockquote — contains a sequence of child blocks."""
    blocks: tuple["Block", ...]


@dataclass(frozen=True)
class CodeBlock:
    """A fenced code block. ``content`` is the literal text, ``info`` is
    the optional info string (typically a language tag).
    """
    content: str
    info: str = ""


@dataclass(frozen=True)
class ThematicBreak:
    """A horizontal rule produced by ``---``, ``***``, or ``___``."""
    pass


# Column alignment for tables. None means "no explicit alignment".
Alignment = str  # one of "left", "center", "right", or None


@dataclass(frozen=True)
class TableCell:
    """One cell in a table row; holds inline content."""
    inlines: tuple[Inline, ...]


@dataclass(frozen=True)
class Table:
    """A GFM pipe table.

    ``headers`` is the single header row (one TableCell per column).
    ``alignments`` is a per-column alignment string ('left', 'center',
    'right', or None for default/no-explicit). ``rows`` is the body —
    each row is a tuple of TableCells, padded/truncated to match the
    header column count if the source row was shorter or longer.
    """
    headers: tuple[TableCell, ...]
    alignments: tuple[str | None, ...]
    rows: tuple[tuple[TableCell, ...], ...]


Block = Union[Paragraph, Heading, List, BlockQuote, CodeBlock, Table, ThematicBreak]


# --- Document root --------------------------------------------------------


@dataclass(frozen=True)
class Document:
    """The top-level AST node."""
    blocks: tuple[Block, ...]
