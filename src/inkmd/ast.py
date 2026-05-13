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
class Strikethrough:
    """``~~struck~~`` (GFM). Contains inline children."""
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
    """A bare URL, ``<url>``, or ``www.``-prefixed link.

    ``url`` is the resolved destination (what a click follows — may be
    prefixed with ``http://`` or ``mailto:`` if the source omitted one).
    ``text`` is what to display — the literal characters from the source.

    For ``<https://example.com>`` the two are identical. For a bare
    ``www.commonmark.org`` the url is ``http://www.commonmark.org`` and
    the text is ``www.commonmark.org``. For an email the url is
    ``mailto:foo@bar.baz`` and the text is ``foo@bar.baz``.
    """
    url: str
    text: str = ""

    def __post_init__(self) -> None:
        # Default the display text to the resolved URL only when the
        # caller did not supply one (covers existing tests that build
        # AutoLink(url=...) directly).
        if not self.text:
            object.__setattr__(self, "text", self.url)


@dataclass(frozen=True)
class Image:
    """``![alt](url "title")`` image reference.

    ``url`` is the image source — a local file path (relative or
    absolute), a ``data:`` URI, or an ``http(s):`` URL (the last only
    fetched when the caller opts in).

    ``alt`` is the alt-text inline content (typed as a tuple of inline
    nodes so the alt text can itself contain emphasis, code spans, etc.
    Per CommonMark section 6.4, alt text is "the textual content of the
    inner inlines", so a consumer that wants alt-as-plain-string flattens
    the tree to text content).

    ``title`` is the optional tooltip-style string from
    ``![alt](url "title")``.

    ``resolved`` is populated by inkmd.image_loader.resolve_images()
    after parse: it carries the loaded image bytes plus pixel
    dimensions when the source was reachable and recognised, or None
    when the source was missing / unsupported. The renderer uses it to
    decide between PDF embedding and the alt-text-italic fallback.
    """
    inlines: tuple["Inline", ...]
    url: str
    title: str = ""
    resolved: object = None  # inkmd.image_loader.ImageData | None


@dataclass(frozen=True)
class HtmlInline:
    """A literal HTML fragment from the source.

    Per CommonMark section 6.6 the parser recognises inline HTML
    (open tags, close tags, comments, processing instructions,
    declarations, CDATA sections) and preserves the literal bytes for
    HTML-output renderers.

    For PDF output, inkmd's render layer interprets a curated allow-list
    of tags with defined PDF semantics (per docs/design/html-passthrough.md);
    unknown tags drop the tag syntax but keep enclosed text content.
    The HtmlInline node is what the parser emits before the render-time
    interpretation runs.
    """
    raw: str


@dataclass(frozen=True)
class Subscript:
    """``<sub>text</sub>`` (HTML allow-list extension)."""
    inlines: tuple["Inline", ...]


@dataclass(frozen=True)
class Superscript:
    """``<sup>text</sup>`` (HTML allow-list extension)."""
    inlines: tuple["Inline", ...]


@dataclass(frozen=True)
class Underline:
    """``<u>text</u>`` (HTML allow-list extension)."""
    inlines: tuple["Inline", ...]


@dataclass(frozen=True)
class Mark:
    """``<mark>text</mark>`` (HTML allow-list extension): highlighted text."""
    inlines: tuple["Inline", ...]


@dataclass(frozen=True)
class Kbd:
    """``<kbd>keys</kbd>`` (HTML allow-list extension): keyboard input."""
    inlines: tuple["Inline", ...]


@dataclass(frozen=True)
class HardBreak:
    """A hard line break.

    Comes from either CommonMark hard-break syntax (``\\\\`` or two-or-
    more trailing spaces before a newline) or the HTML allow-list tag
    ``<br>`` / ``<br/>`` / ``<br />``.
    """
    pass


Inline = Union[
    Text,
    Strong,
    Emphasis,
    Strikethrough,
    Code,
    Link,
    AutoLink,
    Image,
    HtmlInline,
    Subscript,
    Superscript,
    Underline,
    Mark,
    Kbd,
    HardBreak,
]


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

    ``task`` is None for an ordinary list item; True for a GFM task list
    item whose source started with ``[x]`` or ``[X]`` (checked); False
    for one that started with ``[ ]`` (unchecked). The bracket prefix
    is consumed by the parser; it is not visible in ``blocks``.
    """
    blocks: tuple["Block", ...]
    task: bool | None = None


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
    """The top-level AST node.

    ``link_references`` is a tuple of ``(label, url, title)`` triples,
    populated by the parser's first pass when it sees CommonMark link
    reference definitions of the form ``[label]: url "title"``
    (section 6.3). Labels are stored already normalised (Unicode case-
    fold, surrounding whitespace stripped, internal whitespace runs
    collapsed to a single space) so inline resolution can do a direct
    lookup after normalising the reference's label the same way.

    A tuple (not a dict) so Document remains a pure frozen-dataclass
    value type; the parser builds the list, deduplicates first-wins
    per spec, and passes the resulting tuple in. Helper
    ``link_reference_table()`` builds the lookup dict from the tuple.
    """
    blocks: tuple[Block, ...]
    link_references: tuple[tuple[str, str, str], ...] = ()

    def link_reference_table(self) -> dict[str, tuple[str, str]]:
        """Build a label -> (url, title) lookup from ``link_references``.

        First-wins: if the same label appears multiple times in the
        source, the earlier definition is the one kept (CommonMark
        section 6.3 example 213).
        """
        table: dict[str, tuple[str, str]] = {}
        for label, url, title in self.link_references:
            if label not in table:
                table[label] = (url, title)
        return table
