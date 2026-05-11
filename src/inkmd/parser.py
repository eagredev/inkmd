"""Markdown parser.

CommonMark-subset parser, hand-rolled. Two phases:

1. **Block parse**: container-aware walk that maintains a stack of open
   list containers, splits input into blocks. Handles ATX/Setext
   headings, ordered/unordered lists (with nesting, tight/loose
   distinction), and paragraphs.

2. **Inline parse**: walk each block's text and produce inline AST
   nodes — the canonical CommonMark left/right-flanking delimiter run
   algorithm so nested emphasis, underscore delimiters, and backslash
   escapes work correctly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from inkmd.ast import (
    AutoLink,
    Block,
    BlockQuote,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    Heading,
    Inline,
    Link,
    List,
    ListItem,
    Paragraph,
    Strong,
    Table,
    TableCell,
    Text,
)


# --- Public entry --------------------------------------------------------


# When True, the inline tokeniser detects bare URLs (http/https/ftp/www.)
# and email addresses and turns them into AutoLink nodes — the GFM
# autolink extension. Disabled inside `[text](url)` link text since
# CommonMark forbids nested links. Set by ``parse(md, autolinks=...)``;
# read by ``_parse_inlines``.
_AUTOLINKS_ENABLED = True


def parse(text: str, *, autolinks: bool = True) -> Document:
    """Parse a markdown string into an AST.

    Public entry point. Normalises line endings (CRLF / CR → LF),
    expands tabs to 4 spaces, then runs the two-phase pipeline.

    ``autolinks`` controls GFM-style autolinking of bare URLs and email
    addresses. Default True (matches GitHub / common docs sites). Set
    False for strict CommonMark — bare URLs render as plain text.
    """
    global _AUTOLINKS_ENABLED
    prev = _AUTOLINKS_ENABLED
    _AUTOLINKS_ENABLED = autolinks
    try:
        normalised = _normalise(text)
        blocks = _parse_blocks(normalised)
        return Document(blocks=tuple(blocks))
    finally:
        _AUTOLINKS_ENABLED = prev


def _normalise(text: str) -> str:
    """Normalise line endings and tabs per CommonMark §2.2."""
    text = text.replace("\x00", "�")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.expandtabs(4)
    return text


_ATX_MAX_INDENT = 3


# --- Block parser (container-aware) --------------------------------------


@dataclass
class _ItemCtx:
    """Open list item: accumulates child blocks and an in-progress paragraph."""
    blocks: list[Block] = field(default_factory=list)
    paragraph_lines: list[str] = field(default_factory=list)
    # Set when a blank line is seen inside this item — used to detect
    # loose lists (a blank line inside an item forces the parent list loose).
    had_blank_inside: bool = False


@dataclass
class _ListCtx:
    """Open list: a sequence of items plus shared marker style + indent.

    ``marker_indent`` is the absolute column the marker character sits at
    (relative to the original line start). ``content_indent`` is the
    *relative* offset from marker_indent to the item content column, i.e.
    how much each continuation line must be indented past the marker
    column to continue belonging to this list's items.
    """
    ordered: bool
    start: int
    marker_char: str  # '-', '*', '+', or '.' / ')' for ordered
    marker_indent: int  # absolute column the marker sits at
    content_indent: int  # cols of dedent applied at this list's continuation
    items: list[_ItemCtx] = field(default_factory=list)
    blank_before_next_item: bool = False  # any blank between last item and current
    force_loose: bool = False  # set if any item had a blank inside it


def _parse_blocks(text: str) -> list[Block]:
    """Parse ``text`` into a list of block AST nodes.

    Container-aware: maintains a stack of open list containers. Each line
    walks down the stack to determine which containers it continues; the
    remainder is interpreted as a block-level construct (heading, list
    marker, paragraph content, or blank).
    """
    parser = _BlockParser()
    for line in text.split("\n"):
        parser.feed(line)
    return parser.finish()


class _BlockParser:
    """Stateful block-level parser.

    ``doc_blocks`` is the output accumulator for top-level blocks.
    ``list_stack`` is the chain of currently-open lists (deepest last);
    each list's ``items[-1]`` is the open item that new content goes into.
    """

    def __init__(self) -> None:
        self.doc_blocks: list[Block] = []
        self.list_stack: list[_ListCtx] = []
        self._doc_paragraph_lines: list[str] = []
        # Fenced code block state — when active, lines are collected
        # verbatim until the close fence.
        self._code_fence_char: str | None = None
        self._code_fence_len: int = 0
        self._code_indent: int = 0
        self._code_info: str = ""
        self._code_lines: list[str] = []
        # Blockquote state — when active, lines stripped of `>` prefix are
        # accumulated, then parsed recursively into child blocks on close.
        self._in_quote: bool = False
        self._quote_lines: list[str] = []
        # Table state — when active at the document level, body rows are
        # accumulated until a blank or non-row line closes the table.
        self._in_table: bool = False
        self._table_headers: tuple[TableCell, ...] = ()
        self._table_alignments: tuple[str | None, ...] = ()
        self._table_rows: list[tuple[TableCell, ...]] = []

    # --- Public driver ---------------------------------------------------

    def feed(self, line: str) -> None:
        """Process one input line."""
        # Inside a fenced code block, lines are taken verbatim until the
        # matching close fence. Nothing else interrupts.
        if self._code_fence_char is not None:
            if _is_close_fence(line, self._code_fence_char, self._code_fence_len):
                self._close_code_fence()
            else:
                self._code_lines.append(_strip_code_indent(line, self._code_indent))
            return

        # Inside a table at the document level, every non-blank pipe line
        # is a body row; blank or non-row closes the table.
        if self._in_table:
            if line.strip() == "":
                self._close_table()
                return
            cells = _try_table_row(line, len(self._table_headers))
            if cells is None:
                # Not a valid row → close the table and re-feed the line.
                self._close_table()
                # Fall through to normal handling below.
            else:
                self._table_rows.append(cells)
                return

        # Blockquote prefix handling — top-level only for v0.1. Inside
        # lists, `>` is treated as paragraph content.
        if not self.list_stack:
            quote_stripped = _try_blockquote_prefix(line)
            if quote_stripped is not None:
                self._handle_quote_line(quote_stripped)
                return
            if self._in_quote:
                # Non-quote line ends the blockquote (no lazy continuation in v0.1).
                self._close_quote()

        if line.strip() == "":
            self._handle_blank()
            return

        # Compute the line's leading indent column.
        stripped_line = line.lstrip(" ")
        line_indent = len(line) - len(stripped_line)

        # Fence open at top-of-current-container — detect before list logic.
        if not self.list_stack:
            fence_open = _try_fence_open(line)
            if fence_open is not None:
                self._open_code_fence(fence_open)
                return

        # Table detection — at document level only. If the accumulator
        # holds exactly one paragraph line that looks like a row and this
        # line is a delimiter row, commit to table mode.
        if (
            not self.list_stack
            and not self._in_quote
            and len(self._doc_paragraph_lines) == 1
        ):
            header_candidate = self._doc_paragraph_lines[0]
            alignments = _try_table_delimiter(line)
            if alignments is not None:
                headers = _try_table_row(header_candidate, len(alignments))
                if headers is not None:
                    self._doc_paragraph_lines.clear()
                    self._open_table(headers, alignments)
                    return

        # Walk the open list stack outermost-to-innermost. For each list,
        # determine whether this line:
        #   (a) continues an item (indent ≥ list's item content column)
        #   (b) is a sibling marker of that list (indent == marker_indent,
        #       marker style matches) — closes inner lists, starts new item
        #   (c) neither — closes that list and all deeper.
        kept = 0
        sibling: tuple[int, _MarkerInfo] | None = None
        for idx, ctx in enumerate(self.list_stack):
            item_indent = ctx.marker_indent + ctx.content_indent
            if line_indent >= item_indent:
                # Continuation of this list's open item; move on inwards.
                kept = idx + 1
                continue
            # Not deep enough to continue the item. Maybe a sibling marker?
            if line_indent == ctx.marker_indent:
                # The marker sits at ctx.marker_indent absolute; check the
                # marker by stripping exactly that much leading space, so
                # _try_marker sees the marker at column 0 of the remainder.
                marker = _try_marker(line[ctx.marker_indent:])
                if marker is not None and _marker_matches_list(marker, ctx):
                    sibling = (idx, marker)
                    kept = idx + 1
                    break
            # Otherwise this line breaks out of this list (and deeper).
            kept = idx
            break

        # Close all lists deeper than the kept depth.
        while len(self.list_stack) > kept:
            self._close_top_list()

        if sibling is not None:
            # Close current item, open a new sibling item.
            idx, marker = sibling
            list_ctx = self.list_stack[idx]
            self._close_top_item()
            if list_ctx.blank_before_next_item:
                list_ctx.force_loose = True
                list_ctx.blank_before_next_item = False
            list_ctx.items.append(_ItemCtx())
            if marker.content:
                self._add_content_line(marker.content)
            return

        # Dedent the line by the kept lists' total indent so subsequent
        # block-level checks see the line as if it sat at the inner
        # container's column-0.
        if kept > 0:
            inner = self.list_stack[kept - 1]
            absolute_inner_content_col = inner.marker_indent + inner.content_indent
            remaining = line[absolute_inner_content_col:] if line_indent >= absolute_inner_content_col else line.lstrip(" ")
        else:
            remaining = line

        self._handle_content_line(remaining)

    def finish(self) -> list[Block]:
        """Flush any in-progress state and return the top-level blocks."""
        # A fence that's never closed still emits a CodeBlock (EOF closes it).
        if self._code_fence_char is not None:
            self._close_code_fence()
        while self.list_stack:
            self._close_top_list()
        if self._in_quote:
            self._close_quote()
        if self._in_table:
            self._close_table()
        self._flush_doc_paragraph()
        return self.doc_blocks

    # --- Container matching ----------------------------------------------

    # --- Content handling ------------------------------------------------

    def _handle_blank(self) -> None:
        """Process a blank line."""
        # Flush an open paragraph in the deepest open item / document.
        if self.list_stack:
            top = self.list_stack[-1]
            if top.items:
                item = top.items[-1]
                if item.paragraph_lines:
                    self._flush_item_paragraph(item)
                else:
                    item.had_blank_inside = False  # blank before any block in item
                # A blank line *between* items inside a list signals loose.
                # We don't know yet whether next non-blank starts a new item
                # or just continues; record the blank and check at next line.
            top.blank_before_next_item = True
        else:
            self._flush_doc_paragraph()

    def _handle_content_line(self, remaining: str) -> None:
        """Process a non-blank line after list-stack matching."""
        # 1. ATX heading wins always.
        atx = _try_atx_heading(remaining)
        if atx is not None:
            self._flush_current_paragraph()
            level, body = atx
            self._add_block(Heading(level=level, inlines=_parse_inlines(body)))
            return

        # 2. List marker: starts a new list, a new item, or nests.
        marker = _try_marker(remaining)
        if marker is not None:
            # If the marker is at column 0 of the remainder, it's at the
            # current container's "natural" indent.
            self._handle_marker(remaining, marker)
            return

        # 3. Setext underline: if we have an in-progress paragraph in the
        #    current container, the paragraph becomes a heading.
        setext_level = _try_setext_underline(remaining)
        if setext_level is not None and self._has_open_paragraph():
            self._convert_paragraph_to_heading(setext_level)
            return

        # 4. Plain paragraph content.
        self._add_paragraph_line(remaining)

    def _handle_marker(self, remaining: str, marker: "_MarkerInfo") -> None:
        """Process a marker line not already absorbed as a sibling.

        Either opens a new top-level list (no list on stack) or opens a
        nested list inside the deepest open item.
        """
        # ``remaining`` is already dedented past the enclosing lists.
        stripped = remaining.lstrip(" ")
        local_indent = len(remaining) - len(stripped)

        # Flush any open paragraph in the current container before
        # starting the new list.
        self._flush_current_paragraph()

        # Marker indent for the new list, in absolute (line-start) terms,
        # equals the outer-content-column plus the local indent inside it.
        outer_content_col = sum(
            c.content_indent for c in self.list_stack
        ) + sum(c.marker_indent for c in self.list_stack if False)
        # Simpler: outer absolute column is wherever the innermost item's
        # content sits, which is the innermost list's marker_indent +
        # content_indent (or 0 at document level).
        if self.list_stack:
            inner = self.list_stack[-1]
            outer_content_col = inner.marker_indent + inner.content_indent
        else:
            outer_content_col = 0

        new_list = _ListCtx(
            ordered=marker.ordered,
            start=marker.start,
            marker_char=marker.marker_char,
            marker_indent=outer_content_col + local_indent,
            content_indent=marker.marker_width - local_indent,
            items=[_ItemCtx()],
        )
        self.list_stack.append(new_list)
        if marker.content:
            self._add_content_line(marker.content)

    def _add_content_line(self, content: str) -> None:
        """Add ``content`` (already dedented) to the current container.

        Re-runs content through heading / setext detection because the
        first line after a marker can be a heading, e.g. ``- # Title``.
        """
        atx = _try_atx_heading(content)
        if atx is not None:
            level, body = atx
            self._add_block(Heading(level=level, inlines=_parse_inlines(body)))
            return
        self._add_paragraph_line(content)

    # --- Paragraph + block accumulators ----------------------------------

    def _add_paragraph_line(self, line: str) -> None:
        if self.list_stack:
            top = self.list_stack[-1]
            item = top.items[-1]
            # If a blank was seen since this item's last content, it's a
            # blank *inside* this item (because we got here without
            # crossing a sibling marker), so mark loose.
            if top.blank_before_next_item:
                top.force_loose = True
                top.blank_before_next_item = False
            item.paragraph_lines.append(line.strip())
        else:
            self._doc_paragraph_lines.append(line.strip())

    def _add_block(self, block: Block) -> None:
        self._flush_current_paragraph()
        if self.list_stack:
            self.list_stack[-1].items[-1].blocks.append(block)
        else:
            self.doc_blocks.append(block)

    def _flush_current_paragraph(self) -> None:
        if self.list_stack:
            item = self.list_stack[-1].items[-1]
            self._flush_item_paragraph(item)
        else:
            self._flush_doc_paragraph()

    def _flush_item_paragraph(self, item: _ItemCtx) -> None:
        if item.paragraph_lines:
            joined = " ".join(item.paragraph_lines)
            item.blocks.append(Paragraph(inlines=_parse_inlines(joined)))
            item.paragraph_lines.clear()

    def _flush_doc_paragraph(self) -> None:
        if self._doc_paragraph_lines:
            joined = " ".join(self._doc_paragraph_lines)
            self.doc_blocks.append(Paragraph(inlines=_parse_inlines(joined)))
            self._doc_paragraph_lines.clear()

    def _has_open_paragraph(self) -> bool:
        if self.list_stack:
            return bool(self.list_stack[-1].items[-1].paragraph_lines)
        return bool(self._doc_paragraph_lines)

    def _convert_paragraph_to_heading(self, level: int) -> None:
        """Drain the current paragraph accumulator and emit a Heading."""
        if self.list_stack:
            item = self.list_stack[-1].items[-1]
            joined = " ".join(item.paragraph_lines)
            item.paragraph_lines.clear()
            item.blocks.append(Heading(level=level, inlines=_parse_inlines(joined)))
        else:
            joined = " ".join(self._doc_paragraph_lines)
            self._doc_paragraph_lines.clear()
            self.doc_blocks.append(Heading(level=level, inlines=_parse_inlines(joined)))

    # --- Blockquote handling ---------------------------------------------

    def _handle_quote_line(self, stripped: str) -> None:
        """Append a `>`-prefixed line (with prefix already stripped)."""
        # Close any open list before starting a blockquote (since v0.1
        # doesn't support blockquote-inside-list).
        while self.list_stack:
            self._close_top_list()
        # Flush any open paragraph; the blockquote starts a new block.
        if not self._in_quote:
            self._flush_doc_paragraph()
            self._in_quote = True
        self._quote_lines.append(stripped)

    def _close_quote(self) -> None:
        """Recursively parse the accumulated quote lines and emit a BlockQuote."""
        if not self._in_quote:
            return
        inner_text = "\n".join(self._quote_lines)
        self._in_quote = False
        self._quote_lines = []
        inner_blocks = _parse_blocks(inner_text)
        self.doc_blocks.append(BlockQuote(blocks=tuple(inner_blocks)))

    # --- Table handling --------------------------------------------------

    def _open_table(
        self,
        headers: tuple[TableCell, ...],
        alignments: tuple[str | None, ...],
    ) -> None:
        """Start a table; flush any in-progress doc paragraph first."""
        self._flush_doc_paragraph()
        self._in_table = True
        self._table_headers = headers
        self._table_alignments = alignments
        self._table_rows = []

    def _close_table(self) -> None:
        """Emit the accumulated Table block and reset state."""
        if not self._in_table:
            return
        table = Table(
            headers=self._table_headers,
            alignments=self._table_alignments,
            rows=tuple(self._table_rows),
        )
        self._in_table = False
        self._table_headers = ()
        self._table_alignments = ()
        self._table_rows = []
        self.doc_blocks.append(table)

    # --- Fenced code handling --------------------------------------------

    def _open_code_fence(self, fence: "_FenceInfo") -> None:
        """Start a fenced code block."""
        self._flush_current_paragraph()
        self._code_fence_char = fence.char
        self._code_fence_len = fence.length
        self._code_indent = fence.indent
        self._code_info = fence.info
        self._code_lines = []

    def _close_code_fence(self) -> None:
        """Emit the accumulated code lines as a CodeBlock."""
        content = "\n".join(self._code_lines)
        block = CodeBlock(content=content, info=self._code_info)
        self._code_fence_char = None
        self._code_fence_len = 0
        self._code_indent = 0
        self._code_info = ""
        self._code_lines = []
        self._add_block(block)

    # --- Close items / lists ---------------------------------------------

    def _close_top_item(self) -> None:
        """Close the open item in the deepest open list.

        Flushes any in-progress paragraph; recursively closes any nested
        open lists belonging to that item's blocks (handled by caller).
        """
        if not self.list_stack:
            return
        top = self.list_stack[-1]
        if not top.items:
            return
        item = top.items[-1]
        self._flush_item_paragraph(item)
        if item.had_blank_inside:
            top.force_loose = True

    def _close_top_list(self) -> None:
        """Close the deepest open list and append its frozen List node."""
        self._close_top_item()
        ctx = self.list_stack.pop()
        # Decide tight vs loose. Loose if any item had an interior blank,
        # or any pair of items had a blank between them.
        tight = not ctx.force_loose
        items = tuple(ListItem(blocks=tuple(it.blocks)) for it in ctx.items)
        list_node = List(
            ordered=ctx.ordered,
            start=ctx.start,
            tight=tight,
            items=items,
        )
        # Append to parent container.
        if self.list_stack:
            parent_item = self.list_stack[-1].items[-1]
            self._flush_item_paragraph(parent_item)
            parent_item.blocks.append(list_node)
        else:
            self.doc_blocks.append(list_node)


def _marker_matches_list(marker: "_MarkerInfo", ctx: _ListCtx) -> bool:
    """True if a marker can continue an open list as a sibling item."""
    if marker.ordered != ctx.ordered:
        return False
    # Bullet: same marker char (-, *, +). Ordered: same delimiter (. or )).
    return marker.marker_char == ctx.marker_char


# --- Marker recognition ---------------------------------------------------


@dataclass
class _MarkerInfo:
    """Result of parsing a list marker at the start of a line."""
    ordered: bool
    marker_char: str       # for bullet: '-' '*' '+'; for ordered: '.' or ')'
    start: int             # for ordered: starting number; for bullet: 1
    marker_width: int      # chars consumed including the trailing space
    content: str           # remainder of the line after the marker


def _try_marker(line: str) -> _MarkerInfo | None:
    """Parse a list marker at the *start* of ``line`` (post-dedent).

    Returns marker info or None. Up to 3 leading spaces are allowed
    before the marker; further indent is part of the marker's own
    content-column placement so the caller's local_indent reflects it.
    """
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > _ATX_MAX_INDENT:
        return None
    if not stripped:
        return None

    # Bullet marker?
    if stripped[0] in "-*+":
        ch = stripped[0]
        rest = stripped[1:]
        # Must be followed by space or end-of-line.
        if rest and not rest.startswith(" "):
            return None
        content = rest[1:] if rest.startswith(" ") else ""
        # Marker width: indent + 1 (marker) + 1 (space after) = consumed cols
        marker_width = indent + 2 if rest else indent + 1
        return _MarkerInfo(
            ordered=False,
            marker_char=ch,
            start=1,
            marker_width=marker_width,
            content=content,
        )

    # Ordered marker? 1-9 digits then '.' or ')'.
    i = 0
    while i < len(stripped) and stripped[i].isdigit():
        i += 1
    if 0 < i <= 9 and i < len(stripped) and stripped[i] in ".)":
        try:
            start = int(stripped[:i])
        except ValueError:
            return None
        delim = stripped[i]
        rest = stripped[i + 1:]
        if rest and not rest.startswith(" "):
            return None
        content = rest[1:] if rest.startswith(" ") else ""
        marker_width = indent + i + 1 + (1 if rest else 0)
        return _MarkerInfo(
            ordered=True,
            marker_char=delim,
            start=start,
            marker_width=marker_width,
            content=content,
        )
    return None


# --- Heading / Setext recognition ----------------------------------------


def _try_atx_heading(line: str) -> tuple[int, str] | None:
    """Return ``(level, body)`` if ``line`` is an ATX heading, else None.

    CommonMark §4.2: 0-3 spaces of indent, 1-6 ``#``, then either end of
    line or a space before the body. Optional trailing run of ``#``
    (preceded by space) is stripped — interior ``#`` is preserved.
    """
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > _ATX_MAX_INDENT:
        return None
    i = 0
    while i < len(stripped) and stripped[i] == "#":
        i += 1
    if i == 0 or i > 6:
        return None
    rest = stripped[i:]
    if rest and rest[0] != " ":
        return None
    body = rest.strip()
    # Strip optional trailing closing hashes (must be space-separated).
    if body:
        j = len(body)
        while j > 0 and body[j - 1] == "#":
            j -= 1
        if j < len(body) and (j == 0 or body[j - 1] == " "):
            body = body[:j].rstrip()
    return i, body


def _try_setext_underline(line: str) -> int | None:
    """Return 1 if ``line`` is an H1 setext underline, 2 for H2, else None.

    CommonMark §4.3: 0-3 spaces of indent, then a run of ``=`` (H1) or
    ``-`` (H2), with no other non-whitespace characters.
    """
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > _ATX_MAX_INDENT:
        return None
    body = stripped.rstrip()
    if not body:
        return None
    if all(c == "=" for c in body):
        return 1
    if all(c == "-" for c in body):
        return 2
    return None


# --- Blockquote + fenced code recognition --------------------------------


def _try_blockquote_prefix(line: str) -> str | None:
    """Return the line with the ``>`` blockquote prefix stripped, else None.

    CommonMark §5.1: up to 3 spaces of indent, then ``>`` optionally
    followed by one space. The content after the prefix is the
    blockquote's contribution.
    """
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > _ATX_MAX_INDENT:
        return None
    if not stripped or stripped[0] != ">":
        return None
    rest = stripped[1:]
    if rest.startswith(" "):
        rest = rest[1:]
    return rest


@dataclass
class _FenceInfo:
    """Open code fence: marker char, length, indent and info string."""
    char: str       # '`' or '~'
    length: int     # number of fence chars (>= 3)
    indent: int     # leading-space count of the fence line
    info: str       # remainder of the fence line (typically a language name)


def _try_fence_open(line: str) -> _FenceInfo | None:
    """Return ``_FenceInfo`` if ``line`` opens a fenced code block.

    CommonMark §4.5: 0-3 spaces of indent, then 3 or more of ``` `` ``` or
    ``~~~``. The optional info string is whatever follows the fence on
    the same line.
    """
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > _ATX_MAX_INDENT:
        return None
    if not stripped or stripped[0] not in "`~":
        return None
    ch = stripped[0]
    i = 0
    while i < len(stripped) and stripped[i] == ch:
        i += 1
    if i < 3:
        return None
    info = stripped[i:].strip()
    # An info string containing a backtick is invalid for backtick fences.
    if ch == "`" and "`" in info:
        return None
    return _FenceInfo(char=ch, length=i, indent=indent, info=info)


def _is_close_fence(line: str, fence_char: str, fence_len: int) -> bool:
    """True if ``line`` is a closing fence for an open block.

    CommonMark §4.5: closing fence is 0-3 spaces of indent, then ``>=
    fence_len`` of the same fence character, then only whitespace.
    """
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > _ATX_MAX_INDENT:
        return False
    if not stripped or stripped[0] != fence_char:
        return False
    i = 0
    while i < len(stripped) and stripped[i] == fence_char:
        i += 1
    if i < fence_len:
        return False
    return stripped[i:].strip() == ""


def _strip_code_indent(line: str, indent: int) -> str:
    """Strip up to ``indent`` leading spaces from ``line`` (CommonMark §4.5).

    The opening fence's indent is also subtracted from each content line —
    so a fence indented 2 spaces will have its content stripped of 2
    leading spaces (but no more), preserving internal indentation.
    """
    i = 0
    while i < len(line) and i < indent and line[i] == " ":
        i += 1
    return line[i:]


# --- GFM table recognition -----------------------------------------------


def _split_table_row(line: str) -> list[str] | None:
    """Split a pipe-delimited row into raw cell texts, or None if not a row.

    A row must contain at least one ``|``. Leading and trailing pipes are
    optional. Pipes escaped as ``\\|`` inside a cell are preserved as a
    literal ``|`` in the output text (they don't split). Returns a list
    of cell strings with surrounding whitespace stripped.
    """
    stripped = line.strip()
    if not stripped:
        return None
    if "|" not in stripped:
        return None
    # Trim a single leading and trailing unescaped pipe before splitting.
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    # Walk and split on unescaped `|`. Backslash-escaped pipes survive.
    cells: list[str] = []
    buf = ""
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        if ch == "\\" and i + 1 < len(stripped) and stripped[i + 1] == "|":
            buf += "|"
            i += 2
            continue
        if ch == "|":
            cells.append(buf.strip())
            buf = ""
            i += 1
            continue
        buf += ch
        i += 1
    cells.append(buf.strip())
    return cells


def _try_table_delimiter(line: str) -> tuple[str | None, ...] | None:
    """If ``line`` is a GFM table delimiter row, return per-column alignments.

    Each cell must match `:?-+:?` (3+ dashes, optional leading/trailing
    colon for alignment). Returns a tuple of 'left'/'center'/'right'/None.
    """
    cells = _split_table_row(line)
    if cells is None or not cells:
        return None
    alignments: list[str | None] = []
    for cell in cells:
        if not cell:
            return None
        left = cell.startswith(":")
        right = cell.endswith(":")
        core = cell[1:] if left else cell
        core = core[:-1] if right else core
        if not core or any(ch != "-" for ch in core):
            return None
        if len(core) < 1:
            return None
        if left and right:
            alignments.append("center")
        elif right:
            alignments.append("right")
        elif left:
            alignments.append("left")
        else:
            alignments.append(None)
    return tuple(alignments)


def _try_table_row(line: str, n_cols: int) -> tuple[TableCell, ...] | None:
    """Parse ``line`` as a body/header row with ``n_cols`` columns.

    Cells beyond ``n_cols`` are dropped; missing cells are padded with
    empty cells. Each cell's text is parsed for inline markdown. Returns
    None if the line is not a pipe row.
    """
    cells = _split_table_row(line)
    if cells is None:
        return None
    # Normalise length.
    if len(cells) < n_cols:
        cells = cells + [""] * (n_cols - len(cells))
    elif len(cells) > n_cols:
        cells = cells[:n_cols]
    return tuple(TableCell(inlines=_parse_inlines(c)) for c in cells)


# --- Inline parsing (CommonMark emphasis algorithm) ----------------------

# ASCII punctuation per CommonMark §6.2.
_ASCII_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

# Characters that can be backslash-escaped per CommonMark §6.1.
_ESCAPABLE = _ASCII_PUNCT


@dataclass
class _Delim:
    """A delimiter run discovered during tokenisation.

    ``length`` is how many delimiter chars are in the run. The run may
    be consumed in chunks during emphasis resolution: each pairing eats
    1 or 2 chars from each end; remaining chars stay as a shorter run
    or, once exhausted, drop out of the active list.
    """
    char: str           # '*' or '_'
    length: int         # number of unconsumed delimiter chars
    text_idx: int       # index into the tokens list pointing at our text node
    can_open: bool
    can_close: bool


@dataclass
class _Tok:
    """A token in the inline stream.

    Exactly one of ``text`` / ``code`` / ``delim`` / ``link`` / ``autolink``
    is set. Link tokens carry a pre-parsed ``Link`` AST node; emphasis
    resolution skips over them as atomic units (CommonMark forbids nested
    links anyway).
    """
    text: str | None = None
    code: str | None = None
    delim: _Delim | None = None
    link: "Link | None" = None
    autolink: "AutoLink | None" = None


def _parse_inlines(text: str) -> tuple[Inline, ...]:
    """Parse a paragraph's text into a tuple of inline nodes (CommonMark §6).

    Three phases:
      1. Tokenise into Text / Code / Delim runs, expanding backslash
         escapes inline. Code spans are recognised greedily and become
         opaque tokens.
      2. Resolve emphasis: walk the delimiter runs and pair openers
         with closers, rewriting matched pairs into Strong/Emphasis
         nodes embedded back into the token stream.
      3. Coalesce: merge adjacent Text fragments and emit the final
         tuple of inline nodes.
    """
    if not text:
        return ()

    tokens = _tokenise(text)
    _resolve_emphasis(tokens)
    return _emit(tokens)


# --- Phase 1: tokenisation ------------------------------------------------


def _tokenise(text: str) -> list[_Tok]:
    """Walk ``text`` left-to-right, emitting Text / Code / Delim tokens.

    Backslash escapes are folded into Text tokens as their literal char.
    Code spans (`...`) are recognised greedily and emitted as opaque
    tokens. Runs of ``*`` or ``_`` become Delim tokens with their
    flanking properties precomputed.
    """
    tokens: list[_Tok] = []
    buf = ""
    i = 0
    n = len(text)

    def flush_text() -> None:
        nonlocal buf
        if buf:
            tokens.append(_Tok(text=buf))
            buf = ""

    while i < n:
        ch = text[i]

        # Backslash escape: \X where X is ASCII punctuation → literal X.
        if ch == "\\" and i + 1 < n and text[i + 1] in _ESCAPABLE:
            buf += text[i + 1]
            i += 2
            continue

        # Code span: backtick to next backtick (single-backtick form only
        # for v0.0.6; multi-backtick forms are deferred).
        if ch == "`":
            close = text.find("`", i + 1)
            if close != -1:
                flush_text()
                tokens.append(_Tok(code=text[i + 1:close]))
                i = close + 1
                continue

        # Inline link: [text](url) or [text](url "title").
        if ch == "[":
            link_match = _try_inline_link(text, i)
            if link_match is not None:
                link_node, end_pos = link_match
                flush_text()
                tokens.append(_Tok(link=link_node))
                i = end_pos
                continue

        # Autolink: <url> where url looks like a scheme: or email.
        if ch == "<":
            auto_match = _try_autolink(text, i)
            if auto_match is not None:
                auto_node, end_pos = auto_match
                flush_text()
                tokens.append(_Tok(autolink=auto_node))
                i = end_pos
                continue

        # Delimiter run: * or _, one or more of the same char.
        if ch in "*_":
            j = i
            while j < n and text[j] == ch:
                j += 1
            run = text[i:j]
            flush_text()
            # Compute flanking from neighbours.
            prev = text[i - 1] if i > 0 else " "
            nxt = text[j] if j < n else " "
            can_open, can_close = _flanking(ch, prev, nxt)
            # Reserve a text slot — emphasis resolution may rewrite the
            # delim into nested AST, but if it doesn't, the original
            # delimiter chars become literal text.
            tokens.append(_Tok(text=run))
            tokens[-1].delim = _Delim(
                char=ch,
                length=len(run),
                text_idx=len(tokens) - 1,
                can_open=can_open,
                can_close=can_close,
            )
            i = j
            continue

        # GFM autolinks: bare URL or email at a word boundary. Disabled
        # inside `[text](url)` link text (CommonMark forbids nested links)
        # — `parse(autolinks=False)` also turns this off.
        if _AUTOLINKS_ENABLED and _is_autolink_boundary(text, i, buf):
            auto = _try_bare_autolink(text, i)
            if auto is not None:
                auto_node, end_pos = auto
                flush_text()
                tokens.append(_Tok(autolink=auto_node))
                i = end_pos
                continue

        buf += ch
        i += 1

    flush_text()
    return tokens


# Boundary chars that may precede a bare autolink (GFM): start of input,
# whitespace, or one of these "soft" markdown delimiters / punctuation.
_AUTOLINK_PREV_OK = " \t\n([{*_~"


def _is_autolink_boundary(text: str, i: int, buf: str) -> bool:
    """True if position ``i`` is at a valid GFM autolink boundary.

    Either the start of the inline run, or preceded by whitespace /
    soft punctuation. We check `buf` (which holds in-progress text not
    yet flushed) for the previous character if it's non-empty;
    otherwise the previous token in the stream is the last delimiter
    run or the start.
    """
    prev = buf[-1] if buf else (text[i - 1] if i > 0 else " ")
    return prev in _AUTOLINK_PREV_OK


# GFM autolink URL schemes we recognise without explicit `<...>`.
_BARE_URL_SCHEMES = ("https://", "http://", "ftp://")
_BARE_URL_PREFIX = "www."

# Trailing punctuation stripped from a bare URL match (GFM § "extended
# autolinks"). Semicolons aren't in GFM's official list but I find they
# almost always belong to surrounding text not the URL itself.
_BARE_URL_TRAILING_PUNCT = "?!.,:;*_~"

# Chars valid inside a URL body (loose set, RFC 3986-ish).
_URL_BODY_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "._~:/?#[]@!$&'()*+,;=-%"
)

# Email local-part / domain chars.
_EMAIL_LOCAL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789._%+-"
)
_EMAIL_DOMAIN_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789.-"
)


def _try_bare_autolink(text: str, start: int) -> tuple["AutoLink", int] | None:
    """Detect a GFM autolink at ``text[start:]``.

    Returns ``(AutoLink, end_pos)`` or None. Handles three cases:
      1. Scheme-prefixed URL (``https://``, ``http://``, ``ftp://``)
      2. ``www.``-prefixed URL (auto-prefixed with ``http://``)
      3. Bare email address (auto-prefixed with ``mailto:``)
    """
    # 1. Scheme-prefixed.
    for scheme in _BARE_URL_SCHEMES:
        if text.startswith(scheme, start):
            end = _scan_url_body(text, start + len(scheme))
            if end is None:
                return None
            url = text[start:end]
            return AutoLink(url=url), end

    # 2. www.-prefixed.
    if text.startswith(_BARE_URL_PREFIX, start):
        end = _scan_url_body(text, start + len(_BARE_URL_PREFIX))
        if end is None:
            return None
        url = "http://" + text[start:end]
        return AutoLink(url=url), end

    # 3. Email — must have @ within reach and a TLD-like ending.
    if start < len(text) and text[start] in _EMAIL_LOCAL_CHARS:
        end = _scan_email(text, start)
        if end is not None:
            email = text[start:end]
            return AutoLink(url="mailto:" + email), end

    # 4. Bare host.tld/path — extends GFM with a useful real-world case.
    # `linkedin.com/in/dylanmoir`, `github.com/eagredev` and similar
    # should be clickable, but bare hostnames *without* a path stay as
    # text to avoid false positives like "e.g." or "Inc." Capitalised
    # first letter is allowed since some real domains use it (rare).
    if start < len(text) and text[start] in _HOST_CHARS:
        end = _scan_bare_host_with_path(text, start)
        if end is not None:
            url = "http://" + text[start:end]
            return AutoLink(url=url), end

    return None


# Characters allowed in a hostname label (RFC 1035-ish).
_HOST_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
)


def _scan_bare_host_with_path(text: str, start: int) -> int | None:
    """Scan a host.tld/path autolink.

    Requires: one or more dotted DNS-style labels, last one a TLD of
    2+ alpha chars, followed immediately by '/' and a path. The path
    requirement avoids false positives like 'e.g.' or 'Mr.Smith'.
    Returns the end index, or None.
    """
    n = len(text)
    if start >= n or text[start] not in _HOST_CHARS:
        return None
    # Walk labels.
    i = start
    saw_dot = False
    last_label_start = start
    while i < n and text[i] in _HOST_CHARS:
        i += 1
    if i == start:
        return None
    # We now expect '.' to start the next label.
    while i < n and text[i] == ".":
        if i + 1 >= n or text[i + 1] not in _HOST_CHARS:
            break
        i += 1  # past the dot
        saw_dot = True
        last_label_start = i
        while i < n and text[i] in _HOST_CHARS:
            i += 1
    if not saw_dot:
        return None
    # Last label must be a TLD of 2+ alpha chars (no digits, no hyphens).
    tld = text[last_label_start:i]
    if len(tld) < 2 or not tld.isalpha():
        return None
    # Must be followed by '/' (path requirement).
    if i >= n or text[i] != "/":
        return None
    # Scan the path body using the URL scanner.
    return _scan_url_body_after_host(text, i)


def _scan_url_body_after_host(text: str, start: int) -> int:
    """Scan path/query/fragment portion of a URL starting at ``start``
    (which points at the first '/' after the host).

    Trims trailing punctuation and balances parens like _scan_url_body.
    """
    n = len(text)
    i = start
    paren_depth = 0
    while i < n and text[i] in _URL_BODY_CHARS:
        if text[i] == "(":
            paren_depth += 1
        elif text[i] == ")":
            if paren_depth == 0:
                break
            paren_depth -= 1
        i += 1
    while i > start + 1 and text[i - 1] in _BARE_URL_TRAILING_PUNCT:
        i -= 1
    # Trim trailing unbalanced ')'.
    closes = sum(1 for c in text[start:i] if c == ")")
    opens = sum(1 for c in text[start:i] if c == "(")
    while i > start and closes > opens and text[i - 1] == ")":
        i -= 1
        closes -= 1
    return i


def _scan_url_body(text: str, start: int) -> int | None:
    """Scan a URL body starting at ``start`` (after the scheme).

    Honours GFM's balanced-paren rule and trailing-punctuation strip.
    Returns the end index, or None if no valid URL body found
    (e.g. scheme followed immediately by whitespace).
    """
    n = len(text)
    if start >= n or text[start] not in _URL_BODY_CHARS:
        return None
    # Require at least one '.' in the host portion (e.g. https://x is
    # not a valid autolink — needs a dotted host).
    i = start
    host_end = i
    saw_dot = False
    while host_end < n and text[host_end] in _URL_BODY_CHARS and text[host_end] not in "/?#":
        if text[host_end] == ".":
            saw_dot = True
        host_end += 1
    if not saw_dot:
        return None
    # Continue past path/query/fragment.
    i = host_end
    paren_depth = 0
    while i < n and text[i] in _URL_BODY_CHARS:
        if text[i] == "(":
            paren_depth += 1
        elif text[i] == ")":
            if paren_depth == 0:
                break  # unmatched ) belongs to surrounding text
            paren_depth -= 1
        i += 1
    # Trim trailing punctuation per GFM (period, comma, etc).
    while i > start + 1 and text[i - 1] in _BARE_URL_TRAILING_PUNCT:
        i -= 1
    # Trim trailing ')' beyond what the URL opened.
    closes = sum(1 for c in text[start:i] if c == ")")
    opens = sum(1 for c in text[start:i] if c == "(")
    while i > start and closes > opens and text[i - 1] == ")":
        i -= 1
        closes -= 1
    return i


def _scan_email(text: str, start: int) -> int | None:
    """Scan a bare email address starting at ``start``.

    Returns the end index, or None if not an email. Requires
    local-part chars, an @, domain chars containing at least one dot,
    and a TLD of 2+ alpha chars. Trailing `.` etc. (sentence punctuation
    after the email) is stripped, mirroring _scan_url_body.
    """
    n = len(text)
    # Local-part.
    i = start
    while i < n and text[i] in _EMAIL_LOCAL_CHARS:
        i += 1
    if i == start or i >= n or text[i] != "@":
        return None
    local_end = i
    local = text[start:local_end]
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return None
    # Domain — eat greedily, then trim trailing punctuation.
    i += 1  # past @
    domain_start = i
    while i < n and text[i] in _EMAIL_DOMAIN_CHARS:
        i += 1
    # Strip trailing '.' and ',' etc. (sentence punctuation).
    while i > domain_start and text[i - 1] in ".,;:!?":
        i -= 1
    domain = text[domain_start:i]
    if "." not in domain or domain.startswith("."):
        return None
    tld = domain.rsplit(".", 1)[-1]
    if len(tld) < 2 or not tld.isalpha():
        return None
    return i


# --- Link recognition ----------------------------------------------------


def _try_inline_link(text: str, start: int) -> tuple[Link, int] | None:
    """If ``text[start:]`` starts with ``[text](url[ "title"])``, parse it.

    Returns ``(Link, end_pos)`` where end_pos is the index just after the
    closing ``)``. Returns None if the pattern doesn't match. Brackets
    inside link text must be backslash-escaped; nested brackets are not
    supported in v0.1.
    """
    if text[start] != "[":
        return None
    # 1. Find the matching ']'. Backslash escapes pass; nested [ not allowed.
    i = start + 1
    n = len(text)
    text_start = i
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == "]":
            break
        if text[i] == "[":
            # Nested bracket — bail (v0.1 simplification).
            return None
        i += 1
    if i >= n or text[i] != "]":
        return None
    text_end = i
    # 2. Must be followed by '('.
    if i + 1 >= n or text[i + 1] != "(":
        return None
    j = i + 2
    # 3. Skip optional whitespace before URL.
    while j < n and text[j] in " \t":
        j += 1
    # 4. Parse URL: either <...> form or bare-up-to-whitespace-or-).
    url, j = _parse_link_url(text, j)
    if url is None:
        return None
    # 5. Optional title in "..." or '...' or (...).
    while j < n and text[j] in " \t":
        j += 1
    title = ""
    if j < n and text[j] in '"\'':
        quote = text[j]
        j += 1
        title_buf = ""
        while j < n and text[j] != quote:
            if text[j] == "\\" and j + 1 < n:
                title_buf += text[j + 1]
                j += 2
                continue
            title_buf += text[j]
            j += 1
        if j >= n or text[j] != quote:
            return None
        title = title_buf
        j += 1
    # 6. Skip whitespace before closing ')'.
    while j < n and text[j] in " \t":
        j += 1
    if j >= n or text[j] != ")":
        return None
    link_text = text[text_start:text_end]
    # CommonMark forbids nested links — disable autolinks during the
    # inner parse so a bare URL inside link text doesn't become a
    # second annotation overlapping the outer one.
    global _AUTOLINKS_ENABLED
    prev = _AUTOLINKS_ENABLED
    _AUTOLINKS_ENABLED = False
    try:
        inner_inlines = _parse_inlines(link_text)
    finally:
        _AUTOLINKS_ENABLED = prev
    return Link(inlines=inner_inlines, url=url, title=title), j + 1


def _parse_link_url(text: str, start: int) -> tuple[str | None, int]:
    """Parse the URL portion of an inline link. Returns ``(url, next_idx)``.

    Supports the ``<url>`` form (everything until ``>``) and the bare form
    (everything until whitespace or ``)``). Backslash escapes are
    honoured per CommonMark.
    """
    n = len(text)
    if start >= n:
        return None, start
    if text[start] == "<":
        i = start + 1
        buf = ""
        while i < n and text[i] != ">":
            if text[i] == "\n":
                return None, start
            if text[i] == "\\" and i + 1 < n:
                buf += text[i + 1]
                i += 2
                continue
            buf += text[i]
            i += 1
        if i >= n:
            return None, start
        return buf, i + 1
    # Bare URL: until whitespace, ')', or end of text.
    i = start
    buf = ""
    paren_depth = 0
    while i < n:
        ch = text[i]
        if ch in " \t\n":
            break
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            if paren_depth == 0:
                break
            paren_depth -= 1
        if ch == "\\" and i + 1 < n:
            buf += text[i + 1]
            i += 2
            continue
        buf += ch
        i += 1
    if not buf:
        return None, start
    return buf, i


# CommonMark §6.5 autolink scheme regex (simplified): letter then
# 2-31 of letter/digit/plus/dot/dash; or an email-shaped address.
_AUTOLINK_SCHEME = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_AUTOLINK_SCHEME_TAIL = _AUTOLINK_SCHEME + "0123456789+.-"


def _try_autolink(text: str, start: int) -> tuple[AutoLink, int] | None:
    """If ``text[start:]`` is ``<url>``, parse it. Returns (AutoLink, end_pos)."""
    if text[start] != "<":
        return None
    end = text.find(">", start + 1)
    if end == -1:
        return None
    inner = text[start + 1:end]
    if not inner:
        return None
    if " " in inner or "\n" in inner or "<" in inner:
        return None
    # Plausible URI: scheme:rest where scheme starts with a letter and has
    # 2-32 valid scheme chars.
    colon = inner.find(":")
    if colon == -1:
        # Try email shape: local@domain.tld
        if "@" in inner:
            return AutoLink(url="mailto:" + inner), end + 1
        return None
    scheme = inner[:colon]
    if not scheme or scheme[0] not in _AUTOLINK_SCHEME:
        return None
    if not all(c in _AUTOLINK_SCHEME_TAIL for c in scheme[1:]):
        return None
    if not (2 <= len(scheme) <= 32):
        return None
    return AutoLink(url=inner), end + 1


def _flanking(ch: str, prev: str, nxt: str) -> tuple[bool, bool]:
    """Compute (can_open, can_close) for a delimiter run.

    Per CommonMark §6.2:
      - left-flanking: not followed by whitespace AND (not followed by
        punctuation OR preceded by whitespace/punctuation)
      - right-flanking: not preceded by whitespace AND (not preceded by
        punctuation OR followed by whitespace/punctuation)
      - For `*`: can_open ↔ left-flanking, can_close ↔ right-flanking.
      - For `_`: can_open ↔ left-flanking AND (not right-flanking OR
        preceded by punctuation); can_close ↔ right-flanking AND (not
        left-flanking OR followed by punctuation). This is the
        intraword underscore rule.
    """
    prev_ws = prev.isspace() or prev == " "
    nxt_ws = nxt.isspace() or nxt == " "
    prev_punct = prev in _ASCII_PUNCT
    nxt_punct = nxt in _ASCII_PUNCT

    left_flanking = (not nxt_ws) and (not nxt_punct or prev_ws or prev_punct)
    right_flanking = (not prev_ws) and (not prev_punct or nxt_ws or nxt_punct)

    if ch == "*":
        return left_flanking, right_flanking
    # ch == "_"
    can_open = left_flanking and (not right_flanking or prev_punct)
    can_close = right_flanking and (not left_flanking or nxt_punct)
    return can_open, can_close


# --- Phase 2: emphasis resolution ----------------------------------------


def _resolve_emphasis(tokens: list[_Tok]) -> None:
    """Walk the delimiter runs, pair openers with closers, rewrite tokens.

    Implements CommonMark §6.2's ``process_emphasis``. We walk the
    closers left-to-right; for each closer, scan backward for the most
    recent compatible opener; if a match is found, eat 1 or 2 delim
    chars from each side and emit a Strong (length 2) or Emphasis
    (length 1) span spanning the tokens between them.

    The "rule of 3": an opener and closer can pair only if
    ``opener.length + closer.length`` is NOT a multiple of 3, OR each
    of ``opener.length`` and ``closer.length`` IS individually a
    multiple of 3.
    """
    # Walk forward looking for closers; for each, search back for opener.
    i = 0
    while i < len(tokens):
        d = tokens[i].delim
        if d is None or not d.can_close:
            i += 1
            continue

        # Search backward for a matching opener.
        j = i - 1
        opener_idx = -1
        while j >= 0:
            cand = tokens[j].delim
            if cand is not None and cand.can_open and cand.char == d.char:
                # Rule of 3.
                if _can_pair(cand, d):
                    opener_idx = j
                    break
            j -= 1

        if opener_idx == -1:
            # No opener; if this delim can't open either, drop the
            # delim metadata so it stays as literal text.
            if not d.can_open:
                tokens[i].delim = None
            i += 1
            continue

        opener = tokens[opener_idx].delim
        # Eat 2 chars for Strong, else 1 for Emphasis.
        eat = 2 if opener.length >= 2 and d.length >= 2 else 1

        # Build the span over tokens (opener_idx, i).
        inner_tokens = tokens[opener_idx + 1:i]
        inner = _emit_inner(inner_tokens)
        if eat == 2:
            span = Strong(inlines=inner)
        else:
            span = Emphasis(inlines=inner)

        # Trim delim lengths.
        opener.length -= eat
        d.length -= eat

        # Build the replacement slice. Remainders on either side keep
        # their `_Delim` metadata (with reduced length) so the iterative
        # walk can pair them again — e.g. ``***x***`` first emits a
        # Strong consuming 2 chars per side, leaving a 1-char opener and
        # 1-char closer that the next pass pairs as Emphasis around the
        # Strong, producing the correct ``<em><strong>x</strong></em>``.
        new_tokens: list[_Tok] = []
        if opener.length > 0:
            opener_tok = _Tok(text=opener.char * opener.length)
            opener_tok.delim = _Delim(
                char=opener.char,
                length=opener.length,
                text_idx=0,  # unused after rewrite
                can_open=opener.can_open,
                can_close=opener.can_close,
            )
            new_tokens.append(opener_tok)
        span_tok = _Tok()
        span_tok.span = span  # type: ignore[attr-defined]
        new_tokens.append(span_tok)
        if d.length > 0:
            closer_tok = _Tok(text=d.char * d.length)
            closer_tok.delim = _Delim(
                char=d.char,
                length=d.length,
                text_idx=0,
                can_open=d.can_open,
                can_close=d.can_close,
            )
            new_tokens.append(closer_tok)

        tokens[opener_idx:i + 1] = new_tokens
        # Re-walk from the opener position so a still-active opener
        # remainder can be matched by the *current* closer remainder
        # (which is now inside ``new_tokens`` at the original closer's
        # new index). Conceptually we just retry the whole resolution
        # from where the span landed.
        i = opener_idx


def _can_pair(opener: _Delim, closer: _Delim) -> bool:
    """Apply the "rule of 3" from CommonMark §6.2.

    A delimiter run can be both an opener and closer (e.g. when
    surrounded by punctuation). For such ambiguous cases, the rule
    prevents pathological matches.
    """
    if not (opener.can_open and closer.can_close):
        return False
    if opener.char != closer.char:
        return False
    # If either delim can both open and close, the sum of lengths must
    # not be a multiple of 3 — unless each length is individually a
    # multiple of 3.
    if opener.can_close or closer.can_open:
        if (opener.length + closer.length) % 3 == 0 and not (
            opener.length % 3 == 0 and closer.length % 3 == 0
        ):
            return False
    return True


# --- Phase 3: emit AST ----------------------------------------------------


def _emit(tokens: list[_Tok]) -> tuple[Inline, ...]:
    """Walk the resolved token stream and emit the final AST tuple.

    Coalesces adjacent Text fragments. Drops empty Text. Unwraps span
    placeholders into the AST node they carry.
    """
    return _emit_inner(tokens)


def _emit_inner(tokens: list[_Tok]) -> tuple[Inline, ...]:
    out: list[Inline] = []
    text_buf = ""

    def flush() -> None:
        nonlocal text_buf
        if text_buf:
            out.append(Text(content=text_buf))
            text_buf = ""

    for tok in tokens:
        span = getattr(tok, "span", None)
        if span is not None:
            flush()
            out.append(span)
            continue
        if tok.code is not None:
            flush()
            out.append(Code(content=tok.code))
            continue
        if tok.link is not None:
            flush()
            out.append(tok.link)
            continue
        if tok.autolink is not None:
            flush()
            out.append(tok.autolink)
            continue
        if tok.text is not None:
            text_buf += tok.text
            continue

    flush()
    return tuple(out)
