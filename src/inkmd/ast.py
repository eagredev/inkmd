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


# Type alias for inline-level nodes; widens as 0.0.6+ adds Link, Image.
Inline = Union[Text, Strong, Emphasis, Code]


# --- Block nodes ----------------------------------------------------------


@dataclass(frozen=True)
class Paragraph:
    """A block of flowing text composed of inline nodes."""
    inlines: tuple[Inline, ...]


# Type alias for block-level nodes; widens as 0.0.6 adds Heading, List, CodeBlock, etc.
Block = Paragraph


# --- Document root --------------------------------------------------------


@dataclass(frozen=True)
class Document:
    """The top-level AST node."""
    blocks: tuple[Block, ...]
