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

import html.entities
import unicodedata
from dataclasses import dataclass, field

from inkmd.ast import (
    AutoLink,
    Block,
    BlockQuote,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    HardBreak,
    Heading,
    HtmlInline,
    Image,
    Inline,
    Kbd,
    Link,
    Mark,
    List,
    ListItem,
    Paragraph,
    Strikethrough,
    Strong,
    Subscript,
    Superscript,
    Table,
    TableCell,
    Text,
    ThematicBreak,
    Underline,
)


# --- Public entry --------------------------------------------------------


# When True, the inline tokeniser detects bare URLs (http/https/ftp/www.)
# and email addresses and turns them into AutoLink nodes — the GFM
# autolink extension. Disabled inside `[text](url)` link text since
# CommonMark forbids nested links. Set by ``parse(md, autolinks=...)``;
# read by ``_parse_inlines``.
_AUTOLINKS_ENABLED = True

# When True, the inline tokeniser recognises HTML constructs (open and
# close tags, comments, declarations, CDATA, processing instructions)
# and emits HtmlInline AST nodes for them. Set by ``parse(md, html=...)``.
# See docs/design/html-passthrough.md for the v0.2 scope and PDF-render
# allow-list applied later in inkmd.html_filter.
_HTML_PASSTHROUGH_ENABLED = True

# Reference-link lookup table consulted by inline parsing. Populated in
# the block parser's first pass when ``[label]: url "title"`` definitions
# are seen; consulted by ``_try_inline_link_ref`` when it sees a
# ``[text][label]`` / ``[label][]`` / ``[label]`` reference. Maps
# normalised label -> (url, title). Reset on every parse() call.
_LINK_REFS: dict[str, tuple[str, str]] = {}


def parse(
    text: str,
    *,
    autolinks: bool = True,
    html: bool = True,
) -> Document:
    """Parse a markdown string into an AST.

    Public entry point. Normalises line endings (CRLF / CR -> LF),
    expands tabs to 4 spaces, then runs the two-phase pipeline.

    ``autolinks`` controls GFM-style autolinking of bare URLs and email
    addresses. Default True (matches GitHub / common docs sites). Set
    False for strict CommonMark — bare URLs render as plain text.

    ``html`` controls whether inline HTML constructs are recognised
    and preserved in the AST as HtmlInline nodes. Default True (matches
    CommonMark behaviour). Set False to escape every ``<`` as literal
    text (the v0.1 inkmd behaviour).
    """
    global _AUTOLINKS_ENABLED, _HTML_PASSTHROUGH_ENABLED, _LINK_REFS
    prev_auto = _AUTOLINKS_ENABLED
    prev_html = _HTML_PASSTHROUGH_ENABLED
    prev_refs = _LINK_REFS
    _AUTOLINKS_ENABLED = autolinks
    _HTML_PASSTHROUGH_ENABLED = html
    # Two-pass shape: block parsing gathers reference definitions into
    # a shared list (peeling them off paragraph fronts at flush time),
    # then inline parsing during the same walk consults the global
    # table for resolution. Definitions can appear anywhere in the
    # source — a reference earlier in the source can resolve a
    # definition later in the source — because the block parser keeps
    # building the table as it sees more paragraphs while the inline
    # parser only runs once each paragraph flushes.
    #
    # This means a reference whose definition appears AFTER the
    # paragraph that uses it still resolves correctly: the paragraph
    # only flushes (and inline-parses) when the next block starts or
    # at EOF, by which point any subsequent definition has been seen.
    # The trick is that paragraphs CAN'T flush mid-line: a reference
    # in paragraph N can only resolve to a definition in paragraph
    # M < N if M flushed before N. The CommonMark spec works the same
    # way — definitions are document-scoped, not stream-scoped — so
    # we run a full document pre-scan up front to populate _LINK_REFS
    # before any inline parsing runs.
    normalised = _normalise(text)
    refs_list, stripped = _scan_link_references(normalised)
    refs_table: dict[str, tuple[str, str]] = {}
    for label, url, title in refs_list:
        if label not in refs_table:
            refs_table[label] = (url, title)
    _LINK_REFS = refs_table
    try:
        blocks = _parse_blocks(stripped)
        return Document(
            blocks=tuple(blocks),
            link_references=tuple(refs_list),
        )
    finally:
        _AUTOLINKS_ENABLED = prev_auto
        _HTML_PASSTHROUGH_ENABLED = prev_html
        _LINK_REFS = prev_refs


def _normalise_link_label(label: str) -> str:
    """Canonicalise a link reference label per CommonMark section 6.3.

    Steps: Unicode case-fold, strip surrounding whitespace, collapse
    every run of internal whitespace (including newlines / tabs) to a
    single ASCII space. Used both when storing definitions and when
    resolving references so the two sides compare equal regardless of
    case, spacing, or wrapping.
    """
    folded = label.casefold()
    parts = folded.split()
    return " ".join(parts)


def _try_parse_link_ref_def(
    text: str, start: int
) -> tuple[str, str, str, int] | None:
    """Try to parse a CommonMark link reference definition at ``text[start:]``.

    Returns ``(normalised_label, url, title, end_pos)`` on success where
    ``end_pos`` is the offset just after the consumed text (typically
    the newline after the title, or the newline after the URL when no
    title is present, or the end of text). Returns None if the bytes
    at ``start`` do not form a complete reference definition.

    A reference definition (CommonMark section 4.7) is:
        [label]: url
        [label]: url "title"
        [label]:
          url
          "title"

    Up to 3 leading spaces are permitted before the ``[``. The label,
    URL, and title may collectively span up to multiple lines provided
    each component itself is valid; in practice CommonMark allows the
    URL and title to be on separate lines from the label so long as
    no blank line interrupts.
    """
    n = len(text)
    i = start
    # Up to 3 leading spaces.
    indent = 0
    while i < n and indent < 3 and text[i] == " ":
        i += 1
        indent += 1
    if i >= n or text[i] != "[":
        return None
    label_start = i + 1
    i = label_start
    label_buf = ""
    # CommonMark: label is between [ and ]; brackets can be escaped;
    # max 999 chars (we don't enforce — internal use, malicious input
    # truncated by source size). Newlines allowed (but a blank line
    # breaks the definition; we detect that below).
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            label_buf += text[i + 1]
            i += 2
            continue
        if ch == "[":
            return None  # Nested [ not allowed in label.
        if ch == "]":
            break
        if ch == "\n":
            # Newline inside label: ok unless followed by a blank line.
            if i + 1 < n and text[i + 1] == "\n":
                return None
            label_buf += ch
            i += 1
            continue
        label_buf += ch
        i += 1
    if i >= n or text[i] != "]":
        return None
    # Label must contain something other than whitespace.
    if not label_buf.strip():
        return None
    i += 1  # past ']'
    # Required ':'.
    if i >= n or text[i] != ":":
        return None
    i += 1
    # Optional whitespace (including AT MOST one newline) before URL.
    newlines_seen = 0
    while i < n and text[i] in " \t\n":
        if text[i] == "\n":
            newlines_seen += 1
            if newlines_seen > 1:
                return None
        i += 1
    # URL.
    url, i = _parse_link_url(text, i)
    if url is None:
        return None
    # Try to find an optional title. Title must start after whitespace,
    # with at most one newline between URL and title.
    title = ""
    after_url = i
    nl = 0
    j = i
    while j < n and text[j] in " \t":
        j += 1
    if j < n and text[j] == "\n":
        nl += 1
        j += 1
        while j < n and text[j] in " \t":
            j += 1
    if j < n and text[j] in '"\'(':
        quote = text[j]
        close = ")" if quote == "(" else quote
        k = j + 1
        title_buf = ""
        title_terminated = False
        while k < n:
            if (
                text[k] == "\\"
                and k + 1 < n
                and text[k + 1] in _ASCII_PUNCT
            ):
                title_buf += text[k + 1]
                k += 2
                continue
            if text[k] == close:
                title_terminated = True
                break
            if text[k] == "\n":
                # Blank line inside title kills the definition entirely.
                if k + 1 < n and text[k + 1] == "\n":
                    title_terminated = False
                    break
            title_buf += text[k]
            k += 1
        if title_terminated and k < n and text[k] == close:
            # Title only counts if rest of its line is blank.
            after_title = k + 1
            m = after_title
            while m < n and text[m] in " \t":
                m += 1
            if m >= n or text[m] == "\n":
                title = _decode_inline_escapes(title_buf)
                i = m + 1 if m < n else n
                normalised = _normalise_link_label(label_buf)
                return (normalised, _decode_inline_escapes(url), title, i)
            # Title bytes appeared to close, but trailing junk on the
            # same line means we DON'T accept the title. Fall through
            # and accept the bare-URL form if the URL's own line is
            # otherwise clean.
    # No title (or title rejected). Accept the bare-URL form if the
    # URL's line ends cleanly (only whitespace before newline / EOF).
    m = after_url
    while m < n and text[m] in " \t":
        m += 1
    if m >= n:
        i = m
    elif text[m] == "\n":
        i = m + 1
    else:
        return None
    normalised = _normalise_link_label(label_buf)
    return (normalised, _decode_inline_escapes(url), title, i)


def _scan_link_references(
    text: str,
) -> tuple[list[tuple[str, str, str]], str]:
    """Walk ``text`` and collect every link reference definition.

    Pre-scan run once at parse time so inline parsing has a complete
    reference table when it starts. A definition can only begin where a
    paragraph could begin — at the start of the document, after a blank
    line, or after a block construct that closes a paragraph (heading,
    list end, etc.). We mimic that by tracking a "paragraph could start
    here" flag as we scan line-by-line and only attempting a
    reference-def parse when it's true.

    Lines inside a fenced code block or an indented code block are
    skipped — definitions are not allowed there. Returns
    ``(definitions, stripped_text)`` where ``stripped_text`` is the
    input with the consumed reference-definition lines replaced by
    blank lines (so block line numbering is preserved for any future
    diagnostics).
    """
    out: list[tuple[str, str, str]] = []
    lines = text.split("\n")
    n_lines = len(lines)
    in_fence = False
    fence_char = ""
    fence_len = 0
    can_start = True
    i = 0
    consumed_mask = [False] * n_lines
    while i < n_lines:
        line = lines[i]
        # Track code-fence state — definitions inside fences must be ignored.
        if in_fence:
            if _is_close_fence(line, fence_char, fence_len):
                in_fence = False
                fence_char = ""
                fence_len = 0
            i += 1
            can_start = False
            continue
        fence_info = _try_fence_open(line)
        if fence_info is not None:
            in_fence = True
            fence_char = fence_info.char
            fence_len = fence_info.length
            i += 1
            can_start = False
            continue
        if not line.strip():
            can_start = True
            i += 1
            continue
        # ATX heading, thematic break, and blockquote prefix close any
        # would-be paragraph and let the NEXT line start one again. We
        # accept the current line as "not a definition" and re-arm.
        if _try_atx_heading(line) is not None:
            can_start = True
            i += 1
            continue
        if _is_thematic_break(line):
            can_start = True
            i += 1
            continue
        if not can_start:
            i += 1
            continue
        # Lines at 4+ columns of indent are indented code blocks; skip.
        if _leading_indent_cols(line) >= 4:
            can_start = False
            i += 1
            continue
        # Try to parse a definition spanning one or more consecutive lines.
        candidate = "\n".join(lines[i:]) + "\n"
        result = _try_parse_link_ref_def(candidate, 0)
        if result is None:
            can_start = False
            i += 1
            continue
        label, url, title, end_pos = result
        out.append((label, url, title))
        # Count how many source lines we consumed (a definition can
        # span up to 3 logical lines if URL/title are continuation-
        # wrapped). At minimum 1 line, even if the parser returned a
        # zero-length span (shouldn't happen, defensive).
        consumed = candidate[:end_pos].count("\n")
        consumed = max(consumed, 1)
        for k in range(i, min(i + consumed, n_lines)):
            consumed_mask[k] = True
        i += consumed
        can_start = True
    stripped_lines = [
        "" if consumed_mask[k] else lines[k]
        for k in range(n_lines)
    ]
    return out, "\n".join(stripped_lines)


def _strip_for_hardbreak(line: str) -> str:
    """lstrip a paragraph line; trailing whitespace is preserved verbatim.

    The inline tokeniser inspects trailing spaces directly when deciding
    whether to emit a HardBreak (it requires two-or-more spaces before
    a newline). Stripping a single trailing space at flush time would
    also strip meaningful whitespace inside code spans whose content
    happens to be on the last line — so we preserve everything and
    rely on the tokeniser to discriminate.
    """
    return line.lstrip()


def _normalise(text: str) -> str:
    """Normalise line endings and the NUL character per CommonMark §2.2.

    Tabs are NOT expanded here. Per spec, tabs are treated as if expanded
    for indent-counting purposes only — the byte itself is preserved in
    content (code blocks, paragraph text). Indent-aware sites use
    ``_leading_indent_cols()`` to count columns; everything else sees
    the literal tab.
    """
    text = text.replace("\x00", "�")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _leading_indent_cols(line: str) -> int:
    """Return the column position past leading whitespace (CommonMark §2.2).

    Tabs advance to the next multiple-of-4 column. Spaces advance by 1.
    Non-space-non-tab characters terminate the scan. Used wherever
    block parsing needs an indent count without consuming tab bytes.
    """
    col = 0
    for c in line:
        if c == " ":
            col += 1
        elif c == "\t":
            col += 4 - (col % 4)
        else:
            break
    return col


def _strip_leading_cols(line: str, want: int) -> str:
    """Remove exactly ``want`` columns of leading whitespace from ``line``.

    Used when an indented code block consumes 4 leading columns: the
    line may have a literal tab whose first byte represents the
    consumed indent and whose remaining "virtual columns" should be
    re-emitted as spaces in the code content. Returns the remainder
    of the line after that consumption.
    """
    col = 0
    i = 0
    n = len(line)
    while i < n and col < want:
        c = line[i]
        if c == " ":
            col += 1
            i += 1
        elif c == "\t":
            tab_stop = 4 - (col % 4)
            if col + tab_stop <= want:
                col += tab_stop
                i += 1
            else:
                # The tab partially overlaps the want boundary: split it
                # into the consumed portion (drop) and the remainder
                # (re-emit as spaces in the output).
                remainder_spaces = (col + tab_stop) - want
                col = want
                return (" " * remainder_spaces) + line[i + 1:]
        else:
            break
    return line[i:]


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
    # Indented code block accumulator for this item. A line indented at
    # least 4 columns past the item's content column opens or continues
    # this block; blanks are buffered until either another indented line
    # arrives (in which case the buffer becomes in-block blanks) or a
    # non-indented non-blank line arrives (in which case the buffer is
    # dropped as inter-block padding before flushing the block).
    indented_code_lines: list[str] = field(default_factory=list)
    indented_code_blank_buffer: list[str] = field(default_factory=list)


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
        # Indented code block state (CommonMark section 4.4): lines
        # indented by at least 4 spaces become a code block at the
        # document level, unless they would continue a paragraph (lazy
        # continuation). Blanks inside an indented code block are
        # provisionally buffered; if non-indented content follows, the
        # trailing blanks are dropped before emitting the CodeBlock.
        self._indented_code_lines: list[str] = []
        self._indented_code_blank_buffer: list[str] = []
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
            # When the fence is inside a list item, the close fence
            # may be indented up to the item content column + 3. Strip
            # the item content column first so _is_close_fence sees
            # the residual indent as 0-3 like at document level.
            if self.list_stack:
                inner = self.list_stack[-1]
                content_col = inner.marker_indent + inner.content_indent
                # Use tab-aware stripping so a leading \t inside the
                # item is recognised against the content column.
                close_check_line = _strip_leading_cols(line, content_col)
            else:
                close_check_line = line
            if _is_close_fence(
                close_check_line,
                self._code_fence_char,
                self._code_fence_len,
            ):
                self._close_code_fence()
            else:
                self._code_lines.append(_strip_code_indent(line, self._code_indent))
            return

        # Indented code block (CommonMark section 4.4) — document level
        # only. Active when at least 4 leading spaces AND no open
        # paragraph could absorb the line as lazy continuation.
        if (
            self._indented_code_lines
            and not self.list_stack
        ):
            if line.strip() == "":
                # Blank-or-spaces-only line: buffer it. CommonMark
                # preserves the leading-space remainder past column 4
                # if the block continues (example 112), so we buffer
                # the line in its dedented form, and drop the buffer
                # only if the block ends without seeing another
                # indented content line.
                if _leading_indent_cols(line) >= 4:
                    self._indented_code_blank_buffer.append(_strip_leading_cols(line, 4))
                else:
                    self._indented_code_blank_buffer.append("")
                return
            indent_cols = _leading_indent_cols(line)
            if indent_cols >= 4:
                # Flush any buffered blanks as in-block blank lines, then
                # add this line stripped of its first 4 leading columns.
                # Tab-aware so a single leading \t (column 4) is fully
                # consumed; a tab spanning the boundary leaves the
                # remainder as spaces in the code content.
                if self._indented_code_blank_buffer:
                    self._indented_code_lines.extend(self._indented_code_blank_buffer)
                    self._indented_code_blank_buffer.clear()
                self._indented_code_lines.append(_strip_leading_cols(line, 4))
                return
            # Non-indented non-blank: close the indented code block,
            # then fall through to handle this line normally.
            self._close_indented_code()

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
                # Lazy continuation (CommonMark section 5.1): an
                # unprefixed line continues an open paragraph inside
                # the blockquote provided BOTH lines are paragraph-
                # shaped. The previous quoted line must be non-blank
                # AND not itself an indented code block (≥4 spaces)
                # or other non-paragraph construct; the new line must
                # also be paragraph-content shaped (not a new block
                # opener, not a blank).
                prev_line = self._quote_lines[-1] if self._quote_lines else ""
                prev_is_para_shape = (
                    prev_line.strip() != ""
                    and not prev_line.startswith("    ")
                    and _try_atx_heading(prev_line) is None
                    and _try_fence_open(prev_line) is None
                    and _try_marker(prev_line) is None
                    and not _is_thematic_break(prev_line)
                )
                if (
                    line.strip() != ""
                    and prev_is_para_shape
                    and _try_atx_heading(line) is None
                    and _try_fence_open(line) is None
                    and _try_marker(line) is None
                    and not _is_thematic_break(line)
                ):
                    # Setext underline is NOT a blocker for lazy
                    # continuation into a blockquote: the spec says
                    # `===` arriving as a lazy continuation becomes
                    # paragraph text, not a heading promotion
                    # (example 93). The quote's inner block parser
                    # will see it as part of the paragraph because
                    # only the FIRST setext-underline within a single
                    # paragraph's accumulated lines promotes.
                    self._quote_lines.append(line.lstrip(" "))
                    return
                # Non-quote line ends the blockquote.
                self._close_quote()

        if line.strip() == "":
            self._handle_blank()
            return

        # Compute the line's leading indent column. We keep two values:
        # ``line_indent_cols`` is tab-aware (used for the >=4 indented-
        # code-block test and list-stack column comparisons), while
        # ``line_indent`` keeps the older space-count semantics for
        # the marker / sibling-list logic that has not been ported to
        # tab-aware accounting yet (list-stack alignment is space-only
        # in practice for now).
        stripped_line = line.lstrip(" ")
        line_indent = len(line) - len(stripped_line)
        line_indent_cols = _leading_indent_cols(line)

        # Indented code block opener (CommonMark section 4.4). At
        # document level only; inside lists the same 4-space indent
        # belongs to the list's content column. A line indented at
        # least 4 columns (spaces or tab-stop-padded) opens or
        # continues an indented code block provided no open paragraph
        # would absorb it as lazy continuation.
        if (
            not self.list_stack
            and not self._in_quote
            and not self._doc_paragraph_lines
            and not self._in_table
            and line_indent_cols >= 4
        ):
            self._indented_code_lines.append(_strip_leading_cols(line, 4))
            return

        # Fence open at column 0 (no list active) — short-circuit before
        # list-stack walking. Fence-opens inside list items are handled
        # later in _handle_content_line after the list-stack matching has
        # determined which container the fence belongs to.
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
            # Use tab-aware column count so a leading \t is recognised
            # against the item content column (CommonMark example 4).
            if line_indent_cols >= item_indent:
                # Continuation of this list's open item; move on inwards.
                kept = idx + 1
                continue
            # Not deep enough to continue the item. Maybe a sibling marker?
            # CommonMark §5.2 allows a sibling marker whose indent is
            # anywhere from this list's marker column up to (but not
            # reaching) the item content column — so off-by-one
            # indents in a flat bullet list stay siblings, not nested
            # lists (examples 310, 311, 312).
            if ctx.marker_indent <= line_indent < item_indent:
                # CommonMark §4.1: a thematic break wins over a list
                # marker when the bytes are ambiguous. ``* * *`` at the
                # outer-list's marker column is a thematic break, not a
                # sibling item containing ``* *``. Check thematic-break
                # shape BEFORE list-sibling matching at the same column.
                if _is_thematic_break(line[ctx.marker_indent:]):
                    kept = idx
                    break
                # The marker sits at ctx.marker_indent absolute; check the
                # marker by stripping exactly that much leading space, so
                # _try_marker sees the marker at column 0 of the remainder.
                marker = _try_marker(line[line_indent:])
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
        # container's column-0. Tab-aware so a single leading \t at
        # col 0 fully satisfies an inner content col of 4.
        if kept > 0:
            inner = self.list_stack[kept - 1]
            absolute_inner_content_col = inner.marker_indent + inner.content_indent
            if line_indent_cols >= absolute_inner_content_col:
                remaining = _strip_leading_cols(line, absolute_inner_content_col)
            else:
                remaining = line.lstrip(" \t")
        else:
            remaining = line

        # Indented code block inside a list item (CommonMark section
        # 4.4 + 5.2): a line whose indent past the item's content
        # column is at least 4 columns opens or continues an indented
        # code block scoped to the innermost open item. Like the
        # document-level case, this only fires when no open paragraph
        # in the item could absorb the line as lazy continuation.
        if kept > 0:
            list_ctx = self.list_stack[kept - 1]
            item = list_ctx.items[-1]
            remaining_indent_cols = _leading_indent_cols(remaining)
            if (
                remaining_indent_cols >= 4
                and not item.paragraph_lines
            ):
                # A blank line had to separate this from any prior
                # content inside the item — the indented code path
                # only fires when no paragraph is open. If a blank was
                # buffered, the item is necessarily loose.
                if list_ctx.blank_before_next_item:
                    list_ctx.force_loose = True
                    list_ctx.blank_before_next_item = False
                if item.indented_code_blank_buffer:
                    item.indented_code_lines.extend(item.indented_code_blank_buffer)
                    item.indented_code_blank_buffer.clear()
                item.indented_code_lines.append(_strip_leading_cols(remaining, 4))
                return
            if item.indented_code_lines and not item.paragraph_lines:
                # Non-indented non-blank line inside an item with an
                # open indented-code block: close it before falling
                # through to normal content handling.
                self._close_item_indented_code(item)

        self._handle_content_line(remaining)

    def finish(self) -> list[Block]:
        """Flush any in-progress state and return the top-level blocks."""
        # A fence that's never closed still emits a CodeBlock (EOF closes it).
        if self._code_fence_char is not None:
            self._close_code_fence()
        if self._indented_code_lines:
            self._close_indented_code()
        while self.list_stack:
            self._close_top_list()
        if self._in_quote:
            self._close_quote()
        if self._in_table:
            self._close_table()
        self._flush_doc_paragraph()
        return self.doc_blocks

    def _close_indented_code(self) -> None:
        """Emit the accumulated indented code block and reset state.

        Trailing blank lines buffered while we waited to see whether the
        block continued are dropped — they belong to the inter-block
        gap, not the code content.
        """
        if not self._indented_code_lines:
            self._indented_code_blank_buffer.clear()
            return
        content = "\n".join(self._indented_code_lines) + "\n"
        self.doc_blocks.append(CodeBlock(content=content, info=""))
        self._indented_code_lines.clear()
        self._indented_code_blank_buffer.clear()

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
                elif item.indented_code_lines:
                    # Blank inside an open indented code block in this
                    # item: buffer it. If the block continues (next
                    # non-blank is still indented past content column +
                    # 4) we'll re-emit the buffered blanks; otherwise
                    # they get dropped as inter-block padding.
                    item.indented_code_blank_buffer.append("")
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

        # 2. Setext underline: only when an open paragraph is being closed,
        #    `text\n---` becomes Setext H2 (CommonMark §4.1 example 30,
        #    Setext takes priority over thematic break for the same shape).
        setext_level = _try_setext_underline(remaining)
        if setext_level is not None and self._has_open_paragraph():
            self._convert_paragraph_to_heading(setext_level)
            return

        # 3. Thematic break — checked *before* list markers because
        #    `- - -` and `* * *` would otherwise be eaten as bullet
        #    markers. CommonMark §4.1 says thematic break wins.
        if _is_thematic_break(remaining):
            self._add_block(ThematicBreak())
            return

        # 4. Fenced code block. Inside a list item this opens a code
        #    block scoped to the item; at document level the early-out
        #    in feed() handles it before list-stack matching.
        fence_open = _try_fence_open(remaining)
        if fence_open is not None:
            self._open_code_fence(fence_open)
            return

        # 5. List marker: starts a new list, a new item, or nests.
        marker = _try_marker(remaining)
        if marker is not None:
            # CommonMark example 304: an ordered-list marker whose
            # start number is not 1 cannot interrupt a paragraph.
            # Bulleted markers, ordered markers starting with 1, and
            # markers on a new paragraph all proceed normally.
            interrupts_para = self._has_open_paragraph()
            if (
                interrupts_para
                and marker.ordered
                and marker.start != 1
            ):
                self._add_paragraph_line(remaining)
                return
            # CommonMark also forbids list markers (any kind) from
            # interrupting a paragraph when the item content is
            # blank — but that's an unusual edge case; we don't gate
            # on it for v0.2.
            self._handle_marker(remaining, marker)
            return

        # 6. Plain paragraph content.
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
        Also opens an indented code block inside the current item when
        the first content line has 4+ columns of leading whitespace
        (CommonMark example 273 / 274 — marker followed by 5+ spaces
        whose surplus becomes an indented code line).
        """
        atx = _try_atx_heading(content)
        if atx is not None:
            level, body = atx
            self._add_block(Heading(level=level, inlines=_parse_inlines(body)))
            return
        if (
            self.list_stack
            and _leading_indent_cols(content) >= 4
        ):
            item = self.list_stack[-1].items[-1]
            item.indented_code_lines.append(_strip_leading_cols(content, 4))
            return
        self._add_paragraph_line(content)

    # --- Paragraph + block accumulators ----------------------------------

    def _add_paragraph_line(self, line: str) -> None:
        if self.list_stack:
            top = self.list_stack[-1]
            item = top.items[-1]
            # If an indented code block was open in this item, close it
            # before opening a paragraph — paragraph content does not
            # belong to the code block, and any buffered blanks should
            # drop as inter-block padding.
            if item.indented_code_lines:
                self._close_item_indented_code(item)
            # If a blank was seen since this item's last content, it's a
            # blank *inside* this item (because we got here without
            # crossing a sibling marker), so mark loose.
            if top.blank_before_next_item:
                top.force_loose = True
                top.blank_before_next_item = False
            # lstrip-only: preserve trailing whitespace so the inline
            # parser can detect the CommonMark hard-break form
            # (two-or-more trailing spaces before a newline). A single
            # trailing space is meaningless per spec; collapse it so
            # only the genuine hard-break-marker survives.
            item.paragraph_lines.append(_strip_for_hardbreak(line))
        else:
            self._doc_paragraph_lines.append(_strip_for_hardbreak(line))

    def _add_block(self, block: Block) -> None:
        self._flush_current_paragraph()
        if self.list_stack:
            item = self.list_stack[-1].items[-1]
            if item.indented_code_lines:
                self._close_item_indented_code(item)
            item.blocks.append(block)
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
            # Strip trailing whitespace on the LAST line: a hard-break
            # marker at the very end of a paragraph has nothing to break
            # to and degrades to a normal line ending per spec.
            lines = list(item.paragraph_lines)
            lines[-1] = lines[-1].rstrip()
            joined = "\n".join(lines)
            item.blocks.append(Paragraph(inlines=_parse_inlines(joined)))
            item.paragraph_lines.clear()

    def _flush_doc_paragraph(self) -> None:
        if self._doc_paragraph_lines:
            lines = list(self._doc_paragraph_lines)
            lines[-1] = lines[-1].rstrip()
            joined = "\n".join(lines)
            self.doc_blocks.append(Paragraph(inlines=_parse_inlines(joined)))
            self._doc_paragraph_lines.clear()

    def _has_open_paragraph(self) -> bool:
        if self.list_stack:
            return bool(self.list_stack[-1].items[-1].paragraph_lines)
        return bool(self._doc_paragraph_lines)

    def _convert_paragraph_to_heading(self, level: int) -> None:
        """Drain the current paragraph accumulator and emit a Heading.

        Setext headings do not permit a hard-break marker; per spec the
        underline-line trims trailing whitespace on the content lines.
        We rstrip each accumulated line so trailing two-or-more spaces
        do not promote to a HardBreak when the inline parser runs.
        """
        if self.list_stack:
            item = self.list_stack[-1].items[-1]
            lines = [ln.rstrip() for ln in item.paragraph_lines]
            joined = "\n".join(lines)
            item.paragraph_lines.clear()
            item.blocks.append(Heading(level=level, inlines=_parse_inlines(joined)))
        else:
            lines = [ln.rstrip() for ln in self._doc_paragraph_lines]
            joined = "\n".join(lines)
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
        """Start a fenced code block.

        ``_code_indent`` is the number of leading-space columns to strip
        from each content line. At document level that's the fence
        line's own indent; inside a list item it must also include the
        item's content column so subsequent content-aligned lines
        produce code with no spurious leading whitespace.
        """
        self._flush_current_paragraph()
        # Also close any open indented-code-block on the current item;
        # a fenced code block is its own block, not a continuation.
        if self.list_stack:
            item = self.list_stack[-1].items[-1]
            if item.indented_code_lines:
                self._close_item_indented_code(item)
        self._code_fence_char = fence.char
        self._code_fence_len = fence.length
        if self.list_stack:
            inner = self.list_stack[-1]
            content_col = inner.marker_indent + inner.content_indent
            self._code_indent = content_col + fence.indent
        else:
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
        if item.indented_code_lines:
            self._close_item_indented_code(item)
        if item.had_blank_inside:
            top.force_loose = True

    def _close_item_indented_code(self, item: _ItemCtx) -> None:
        """Emit the accumulated indented code block for ``item`` and clear.

        Trailing buffered blanks (blanks seen while the block might
        have continued) are dropped — they belong to the inter-block
        gap between the code block and whatever follows, not to the
        code content.
        """
        if not item.indented_code_lines:
            item.indented_code_blank_buffer.clear()
            return
        content = "\n".join(item.indented_code_lines) + "\n"
        item.blocks.append(CodeBlock(content=content, info=""))
        item.indented_code_lines.clear()
        item.indented_code_blank_buffer.clear()

    def _close_top_list(self) -> None:
        """Close the deepest open list and append its frozen List node."""
        self._close_top_item()
        ctx = self.list_stack.pop()
        # Decide tight vs loose. Loose if any item had an interior blank,
        # or any pair of items had a blank between them.
        tight = not ctx.force_loose
        items = tuple(_finalise_item(it) for it in ctx.items)
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


def _finalise_item(it: _ItemCtx) -> ListItem:
    """Build the immutable ListItem from a mutable _ItemCtx.

    Also detects the GFM task-list-item prefix on the first paragraph
    line: ``[ ]``, ``[x]``, or ``[X]`` followed by at least one space.
    When found, the prefix is removed from the paragraph and the
    ``task`` flag is set (False for unchecked, True for checked).
    """
    blocks = tuple(it.blocks)
    task = None

    # GFM places the task marker at the start of the FIRST paragraph
    # of the item. We inspect the raw paragraph_lines if any — but by
    # the time _finalise_item runs the paragraph has already been
    # flushed into blocks. Look at the first inline of the first
    # Paragraph instead.
    if blocks and isinstance(blocks[0], Paragraph):
        p = blocks[0]
        if p.inlines and isinstance(p.inlines[0], Text):
            head = p.inlines[0].content
            if len(head) >= 4 and head[0] == "[" and head[2] == "]" and head[3] == " ":
                marker = head[1]
                if marker == " ":
                    task = False
                elif marker in ("x", "X"):
                    task = True
                if task is not None:
                    # Strip the "[ ] " / "[x] " prefix from the first
                    # inline. If the result is empty the Text node
                    # disappears.
                    new_head = head[4:]
                    new_first = (Text(new_head),) if new_head else ()
                    new_inlines = new_first + p.inlines[1:]
                    new_para = Paragraph(inlines=new_inlines)
                    blocks = (new_para,) + blocks[1:]

    return ListItem(blocks=blocks, task=task)


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
        # Must be followed by space, tab, or end-of-line.
        if rest and rest[0] not in " \t":
            return None
        # Count the run of additional spaces / tabs (CommonMark section
        # 5.2): the content column is marker + 1 + min(extra_ws, 3).
        # If more than 4 cols of trailing whitespace, only consume 1
        # (the required space) so the surplus becomes content indent.
        extra = 0
        j = 0
        # _leading_indent_cols-like accounting on ``rest``.
        col = 0
        while j < len(rest):
            c = rest[j]
            if c == " ":
                col += 1
                j += 1
            elif c == "\t":
                col += 4 - (col % 4)
                j += 1
            else:
                break
        # CommonMark: if ``rest`` is whitespace-only, treat as empty
        # marker (content col = marker col + 1). Otherwise content
        # consumes 1 + (1..4) cols of whitespace; >=5 cols means
        # consume only 1 and let the surplus carry into content.
        ws_cols = col
        is_blank_rest = j >= len(rest)
        if is_blank_rest:
            marker_width = indent + 1
            content = ""
        elif ws_cols >= 5:
            marker_width = indent + 2  # marker + 1 space
            content = rest[1:]
        else:
            marker_width = indent + 1 + ws_cols
            content = rest[j:]
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
        if rest and rest[0] not in " \t":
            return None
        # CommonMark §5.2 content-column rule (see bullet branch above).
        col = 0
        j = 0
        while j < len(rest):
            c = rest[j]
            if c == " ":
                col += 1
                j += 1
            elif c == "\t":
                col += 4 - (col % 4)
                j += 1
            else:
                break
        ws_cols = col
        is_blank_rest = j >= len(rest)
        marker_chars = i + 1  # digits + delim
        if is_blank_rest:
            marker_width = indent + marker_chars
            content = ""
        elif ws_cols >= 5:
            marker_width = indent + marker_chars + 1
            content = rest[1:]
        else:
            marker_width = indent + marker_chars + ws_cols
            content = rest[j:]
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


def _is_thematic_break(line: str) -> bool:
    """True if ``line`` is a CommonMark §4.1 thematic break.

    3+ ``-``, ``*``, or ``_`` characters (all the same), optional spaces
    or tabs between them, optional 0-3 leading-space indent, optional
    trailing whitespace.
    """
    stripped = line.lstrip(" ")
    indent = len(line) - len(stripped)
    if indent > _ATX_MAX_INDENT:
        return False
    body = stripped.rstrip()
    if not body:
        return False
    # Remove spaces/tabs from the body; what's left should be 3+ of the same char.
    compact = body.replace(" ", "").replace("\t", "")
    if len(compact) < 3:
        return False
    ch = compact[0]
    if ch not in "-*_":
        return False
    return all(c == ch for c in compact)


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
    followed by one space (or a tab whose first column is consumed and
    whose remaining columns survive as spaces). The content after the
    prefix is the blockquote's contribution.
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
    elif rest.startswith("\t"):
        # A tab immediately after `>` is treated as if expanded with
        # the `>` at column 0: one column goes to the prefix's
        # optional-space slot, the remaining tab columns become
        # content. Full handling needs virtual-column accounting that
        # propagates through subsequent indented-code-block detection;
        # the simple substitution here suffices for paragraph content
        # but not for nested code blocks (CommonMark example 6
        # stays failing; queued for v0.3 list/quote indent refactor).
        rest = "  " + rest[1:]
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
    # CommonMark sections 6.1 + 6.5: backslash escapes and entity refs
    # inside the info string are decoded.
    info = _decode_inline_escapes(info)
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

# ASCII punctuation per CommonMark §6.1 (backslash-escapable).
_ASCII_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")


# CommonMark §6.5 entity / numeric character references.
#
# Three forms:
#   &name;     — must be a valid HTML5 entity (with semicolon)
#   &#NNN;     — decimal, 1-7 digits
#   &#xHH;     — hex, 1-6 digits
#
# Invalid forms (unknown name, NUL, out-of-range, missing semicolon)
# stay literal per CommonMark — UNLIKE stdlib html.unescape which
# silently does its best. We need strict behaviour.
#
# The html5 entity table from the stdlib only stores the WITH-SEMICOLON
# variants for CommonMark; CommonMark requires the semicolon for every
# entity reference (including the historically-bare ones like ``&copy``).
_HTML5_NAMED = {
    k[:-1]: v for k, v in html.entities.html5.items() if k.endswith(";")
}


def _find_matching_backticks(text: str, start: int, n: int) -> int | None:
    """Return the index of a run of EXACTLY ``n`` backticks starting at
    or after ``start``, or None if no such run exists in the input.
    """
    i = start
    end = len(text)
    while i < end:
        if text[i] != "`":
            i += 1
            continue
        j = i
        while j < end and text[j] == "`":
            j += 1
        if j - i == n:
            return i
        i = j
    return None


def _decode_entities(s: str) -> str:
    """Decode every recognised entity / numeric reference in ``s``.

    Used for contexts (link destinations, link titles, code fence info
    strings) where the inline tokeniser does not run but entities are
    still meaningful. Unknown ``&...;`` sequences stay literal.
    """
    if "&" not in s:
        return s
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "&":
            ent = _try_entity_ref(s, i)
            if ent is not None:
                out.append(ent[0])
                i = ent[1]
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _decode_inline_escapes(s: str) -> str:
    """Apply CommonMark inline-text decoding in one left-to-right pass.

    Used in contexts (link destinations, link titles, code fence info
    strings) where the inline tokeniser does not run but backslash
    escapes and entity references are still meaningful.

    Per CommonMark section 6.1, ``\\X`` produces literal X when X is
    ASCII punctuation, and leaves the backslash alone otherwise. Per
    section 6.5, ``&name;`` / ``&#N;`` / ``&#xH;`` decode to the
    referenced character. The single-pass shape matters: ``\\&amp;``
    must stay literally ``&amp;`` (the backslash escapes the ``&``;
    once consumed as a literal it does not re-enter entity decoding).
    """
    if "\\" not in s and "&" not in s:
        return s
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n and s[i + 1] in _ESCAPABLE:
            out.append(s[i + 1])
            i += 2
            continue
        if s[i] == "&":
            ent = _try_entity_ref(s, i)
            if ent is not None:
                out.append(ent[0])
                i = ent[1]
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _try_entity_ref(text: str, start: int) -> tuple[str, int] | None:
    """Try to recognise an entity reference at text[start:].

    Returns (decoded_chars, end_index_after_semicolon) or None.
    On success, end_index points just past the closing ``;``.
    """
    # Must start with '&'
    if start >= len(text) or text[start] != "&":
        return None
    # Find the closing semicolon within a reasonable window.
    # Longest valid: &CounterClockwiseContourIntegral; (33 chars) plus a
    # safety margin. Numeric: &#NNNNNNN; (10) or &#xHHHHHH; (10).
    semi = text.find(";", start + 1, start + 64)
    if semi == -1:
        return None
    inner = text[start + 1:semi]
    if not inner:
        return None

    # Numeric: &#NNN; or &#xNN; / &#XNN;
    if inner[0] == "#":
        body = inner[1:]
        if not body:
            return None
        if body[0] in "xX":
            digits = body[1:]
            if not digits or len(digits) > 6:
                return None
            if not all(c in "0123456789abcdefABCDEF" for c in digits):
                return None
            cp = int(digits, 16)
        else:
            if len(body) > 7:
                return None
            if not body.isdigit():
                return None
            cp = int(body)
        # CommonMark: NUL and out-of-range -> U+FFFD.
        if cp == 0 or cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
            return "�", semi + 1
        return chr(cp), semi + 1

    # Named entity: look up in html5 table (with-semicolon variants only).
    if inner in _HTML5_NAMED:
        return _HTML5_NAMED[inner], semi + 1

    return None

# Characters that can be backslash-escaped per CommonMark §6.1.
_ESCAPABLE = _ASCII_PUNCT


def _is_punctuation(c: str) -> bool:
    """Per CommonMark 0.31.2 §6.2, a punctuation character for emphasis
    flanking is any ASCII punctuation OR any character in Unicode general
    categories P* (punctuation) or S* (symbols).

    The S* part is what makes currency symbols like ``$``, ``£``, ``€``,
    ``¥`` count as punctuation — which means ``*$*alpha`` does NOT open
    emphasis, even though ``*x*alpha`` does.
    """
    if not c:
        return False
    if c in _ASCII_PUNCT:
        return True
    cat = unicodedata.category(c)
    return cat[0] in ("P", "S")


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
    / ``image`` is set. Link / image tokens carry pre-parsed AST nodes;
    emphasis resolution skips over them as atomic units (CommonMark
    forbids nested links anyway).
    """
    text: str | None = None
    code: str | None = None
    delim: _Delim | None = None
    link: "Link | None" = None
    autolink: "AutoLink | None" = None
    image: "Image | None" = None
    html: "HtmlInline | None" = None
    hardbreak: bool = False


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

        # CommonMark hard line break (backslash form): backslash
        # immediately before a newline becomes a <br />, NOT a backslash
        # escape. Must be checked before the generic backslash-escape
        # branch below. Spec section 6.7.
        if ch == "\\" and i + 1 < n and text[i + 1] == "\n":
            flush_text()
            tokens.append(_Tok(hardbreak=True))
            # Consume the backslash + newline, then any leading
            # whitespace on the next line (spec strips it).
            i += 2
            while i < n and text[i] in " \t":
                i += 1
            continue

        # Backslash escape: \X where X is ASCII punctuation → literal X.
        if ch == "\\" and i + 1 < n and text[i + 1] in _ESCAPABLE:
            buf += text[i + 1]
            i += 2
            continue

        # CommonMark hard line break (trailing-spaces form): two-or-more
        # trailing spaces before a newline -> <br />. Tabs do not count
        # per the spec.
        if ch == " ":
            # Look ahead for run of spaces then a newline.
            k = i
            while k < n and text[k] == " ":
                k += 1
            if k - i >= 2 and k < n and text[k] == "\n":
                flush_text()
                tokens.append(_Tok(hardbreak=True))
                # Consume the spaces, the newline, and any leading
                # whitespace on the next line.
                i = k + 1
                while i < n and text[i] in " \t":
                    i += 1
                continue
            # Not a hard break — fall through; the space becomes part
            # of the running text buffer.

        # Entity / numeric character reference (CommonMark §6.5):
        # &name; | &#NNN; | &#xHH;. Unknown references stay literal.
        if ch == "&":
            ent = _try_entity_ref(text, i)
            if ent is not None:
                decoded, end_pos = ent
                buf += decoded
                i = end_pos
                continue

        # Code span: a run of N backticks opens, closed by the next run
        # of EXACTLY N backticks (CommonMark §6.1). Content has internal
        # newlines collapsed to spaces, plus one optional leading and
        # trailing space stripped together if the result still contains
        # a non-space.
        if ch == "`":
            run_end = i
            while run_end < n and text[run_end] == "`":
                run_end += 1
            run_len = run_end - i
            close_start = _find_matching_backticks(text, run_end, run_len)
            if close_start is not None:
                content = text[run_end:close_start]
                # Internal line-endings -> space.
                content = content.replace("\r\n", "\n").replace("\r", "\n")
                content = content.replace("\n", " ")
                # Strip one leading and trailing space iff both exist and
                # the body has at least one non-space character.
                if (
                    len(content) >= 2
                    and content[0] == " "
                    and content[-1] == " "
                    and content.strip()
                ):
                    content = content[1:-1]
                flush_text()
                tokens.append(_Tok(code=content))
                i = close_start + run_len
                continue
            # No matching close: emit the backticks as literal text.
            buf += text[i:run_end]
            i = run_end
            continue

        # Inline image: ![alt](url) — checked before `[` so the `!`
        # prefix isn't consumed as text. Reference image variants
        # ``![alt][label]``, ``![alt][]``, and ``![alt]`` fall through
        # to the same ``!`` branch if the inline form fails.
        if ch == "!":
            image_match = _try_inline_image(text, i)
            if image_match is not None:
                image_node, end_pos = image_match
                flush_text()
                tokens.append(_Tok(image=image_node))
                i = end_pos
                continue
            image_ref_match = _try_reference_image(text, i)
            if image_ref_match is not None:
                image_node, end_pos = image_ref_match
                flush_text()
                tokens.append(_Tok(image=image_node))
                i = end_pos
                continue

        # Inline link: [text](url) or [text](url "title"). Reference-style
        # variants ``[text][label]``, ``[label][]``, and ``[label]``
        # fall through to ``_try_reference_link`` when the inline form
        # doesn't match.
        if ch == "[":
            link_match = _try_inline_link(text, i)
            if link_match is not None:
                link_node, end_pos = link_match
                flush_text()
                tokens.append(_Tok(link=link_node))
                i = end_pos
                continue
            ref_match = _try_reference_link(text, i)
            if ref_match is not None:
                link_node, end_pos = ref_match
                flush_text()
                tokens.append(_Tok(link=link_node))
                i = end_pos
                continue

        # Autolink: <url> where url looks like a scheme: or email.
        # HTML inline: <tag ...>, </tag>, <!--...-->, <![CDATA[...]]>,
        # etc. Autolink wins for the canonical URL form; HTML scanner
        # picks up everything else that starts with `<`.
        if ch == "<":
            auto_match = _try_autolink(text, i)
            if auto_match is not None:
                auto_node, end_pos = auto_match
                flush_text()
                tokens.append(_Tok(autolink=auto_node))
                i = end_pos
                continue
            if _HTML_PASSTHROUGH_ENABLED:
                html_match = _try_html_tag(text, i)
                if html_match is not None:
                    raw, end_pos = html_match
                    flush_text()
                    tokens.append(_Tok(html=HtmlInline(raw=raw)))
                    i = end_pos
                    continue

        # Delimiter run: * / _ / ~, one or more of the same char.
        if ch in "*_~":
            j = i
            while j < n and text[j] == ch:
                j += 1
            run = text[i:j]
            # GFM strikethrough: 1 or 2 tildes can open/close. Runs of
            # 3 or more tildes are literal text per the GFM reference.
            if ch == "~" and len(run) > 2:
                buf += run
                i = j
                continue
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
            literal = text[start:end]
            return AutoLink(url=literal, text=literal), end

    # 2. www.-prefixed.
    if text.startswith(_BARE_URL_PREFIX, start):
        end = _scan_url_body(text, start + len(_BARE_URL_PREFIX))
        if end is None:
            return None
        literal = text[start:end]
        return AutoLink(url="http://" + literal, text=literal), end

    # 3. Email — must have @ within reach and a TLD-like ending.
    if start < len(text) and text[start] in _EMAIL_LOCAL_CHARS:
        end = _scan_email(text, start)
        if end is not None:
            email = text[start:end]
            return AutoLink(url="mailto:" + email, text=email), end

    # 4. Bare host.tld/path — extends GFM with a useful real-world case.
    # `linkedin.com/in/dylanmoir`, `github.com/eagredev` and similar
    # should be clickable, but bare hostnames *without* a path stay as
    # text to avoid false positives like "e.g." or "Inc." Capitalised
    # first letter is allowed since some real domains use it (rare).
    if start < len(text) and text[start] in _HOST_CHARS:
        end = _scan_bare_host_with_path(text, start)
        if end is not None:
            literal = text[start:end]
            return AutoLink(url="http://" + literal, text=literal), end

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
    parsed = _try_link_body(text, start)
    if parsed is None:
        return None
    text_start, text_end, url, title, end_pos = parsed
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
    return Link(inlines=inner_inlines, url=url, title=title), end_pos


def _try_inline_image(text: str, start: int) -> tuple[Image, int] | None:
    """If ``text[start:]`` starts with ``![alt](url[ "title"])``, parse it.

    Per CommonMark §6.4, image alt text is the same shape as link text;
    parsers reuse the link-body machinery. The leading ``!`` differs.
    """
    if text[start] != "!" or start + 1 >= len(text) or text[start + 1] != "[":
        return None
    parsed = _try_link_body(text, start + 1)
    if parsed is None:
        return None
    text_start, text_end, url, title, end_pos = parsed
    alt = text[text_start:text_end]
    # Parse the alt text as inline content. CommonMark says emphasis,
    # code spans etc. inside alt are AST-meaningful even though typical
    # renderers flatten them to plain text for HTML alt attributes.
    inner_inlines = _parse_inlines(alt)
    return Image(inlines=inner_inlines, url=url, title=title), end_pos


def _parse_bracketed_text(text: str, start: int) -> tuple[int, int, int] | None:
    """Parse a ``[...]`` span starting at ``text[start]``.

    Returns ``(text_start, text_end, end_pos)`` where ``text_start`` is
    just past the ``[`` and ``end_pos`` is just past the closing ``]``,
    or None if no matching ``]`` is found. Backslash escapes pass
    through; nested ``[`` is rejected (the spec disallows nested
    references and matched-bracket counting is simpler than the
    full CommonMark "find matching ] across nested brackets" rule —
    a v0.3 refinement if real-world cases demand it).
    """
    if start >= len(text) or text[start] != "[":
        return None
    i = start + 1
    n = len(text)
    text_start = i
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "]":
            return text_start, i, i + 1
        if ch == "[":
            return None
        i += 1
    return None


def _resolve_reference(
    label: str,
) -> tuple[str, str] | None:
    """Look up ``label`` in the global ``_LINK_REFS`` table.

    Returns ``(url, title)`` on hit, or None on miss. Backslash escapes
    inside the reference label are decoded (so ``[foo\\]bar]`` resolves
    against the same key as ``[foo]: ...`` would store under
    ``foo]bar``), then the result is normalised the same way as on the
    storing side.
    """
    decoded = _decode_inline_escapes(label)
    key = _normalise_link_label(decoded)
    if not key:
        return None
    return _LINK_REFS.get(key)


def _try_reference_link(
    text: str, start: int
) -> tuple[Link, int] | None:
    """Try to parse a reference-style link at ``text[start:]``.

    Recognises the three CommonMark reference forms (section 6.3):

      * ``[text][label]``  — full reference
      * ``[label][]``      — collapsed reference (text === label)
      * ``[label]``        — shortcut reference (no second brackets)

    Returns ``(Link, end_pos)`` on a successful lookup against
    ``_LINK_REFS``; otherwise returns None and the caller falls back to
    treating the bytes as literal text.

    The two-bracket forms are tried first; if the second-bracket span
    is present but does not resolve, parsing of THIS construct fails
    entirely (the bytes go through as literal text). The shortcut form
    is only attempted when no second-bracket span follows.
    """
    first = _parse_bracketed_text(text, start)
    if first is None:
        return None
    text_start, text_end, end_first = first
    first_label = text[text_start:text_end]
    n = len(text)
    # Full / collapsed reference: another `[...]` follows immediately.
    if end_first < n and text[end_first] == "[":
        second = _parse_bracketed_text(text, end_first)
        if second is None:
            return None
        s_text_start, s_text_end, end_second = second
        second_label = text[s_text_start:s_text_end]
        # Collapsed: ``[label][]`` — empty second bracket means use first
        # label for lookup; visible text is also the first label.
        if not second_label.strip():
            resolved = _resolve_reference(first_label)
            if resolved is None:
                return None
            url, title = resolved
            return _build_reference_link(first_label, url, title), end_second
        # Full: ``[text][label]`` — lookup uses second label; visible
        # text is the first bracket content.
        resolved = _resolve_reference(second_label)
        if resolved is None:
            return None
        url, title = resolved
        return _build_reference_link(first_label, url, title), end_second
    # Shortcut form: ``[label]`` — lookup uses the bracketed text.
    resolved = _resolve_reference(first_label)
    if resolved is None:
        return None
    url, title = resolved
    return _build_reference_link(first_label, url, title), end_first


def _try_reference_image(
    text: str, start: int
) -> tuple[Image, int] | None:
    """Try to parse a reference-style image at ``text[start:]``.

    Mirrors ``_try_reference_link`` but expects a leading ``!`` and
    builds an Image node. The visible alt text comes from the first
    bracket content; the URL/title come from the reference table.
    """
    if start >= len(text) or text[start] != "!":
        return None
    if start + 1 >= len(text) or text[start + 1] != "[":
        return None
    inner = _try_reference_link(text, start + 1)
    if inner is None:
        return None
    link, end_pos = inner
    return Image(inlines=link.inlines, url=link.url, title=link.title), end_pos


def _build_reference_link(visible_label: str, url: str, title: str) -> Link:
    """Build a Link node for a reference, parsing visible text as inline.

    Reference resolution disables inner autolinks (per the same rule
    inline links use) so a bare URL appearing inside reference text
    doesn't become a nested AutoLink overlapping the outer Link.
    """
    global _AUTOLINKS_ENABLED
    prev = _AUTOLINKS_ENABLED
    _AUTOLINKS_ENABLED = False
    try:
        inner_inlines = _parse_inlines(visible_label)
    finally:
        _AUTOLINKS_ENABLED = prev
    return Link(inlines=inner_inlines, url=url, title=title)


def _try_link_body(
    text: str, start: int
) -> tuple[int, int, str, str, int] | None:
    """Shared body parser for ``[X](url "title")`` style constructs.

    Returns ``(text_start, text_end, url, title, end_pos)`` where the
    caller is responsible for interpreting ``text[text_start:text_end]``
    as inline content (link text or image alt) and constructing the
    appropriate AST node. Returns None if the pattern does not match.
    """
    if text[start] != "[":
        return None
    i = start + 1
    n = len(text)
    text_start = i
    # 1. Find the matching ']'. Backslash escapes pass; nested links
    # are forbidden by spec (a ``[`` inside the link text rejects the
    # parse), BUT an image-inside-link is allowed: an embedded
    # ``![alt](url)`` or ``![alt][ref]`` inside link text is part of
    # the link's content, not a parse failure (CommonMark example 517).
    # We handle this by recognising a leading ``!`` followed by ``[``
    # and skipping over the matching bracket pair.
    depth = 0
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == "]":
            if depth == 0:
                break
            depth -= 1
            i += 1
            continue
        if text[i] == "[":
            # Plain ``[`` inside link text is allowed only as the
            # start of an inline image (``![``); the bare bracket
            # case still rejects per spec.
            if i > start + 1 and text[i - 1] == "!":
                depth += 1
                i += 1
                continue
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
    while j < n and text[j] in " \t\n":
        j += 1
    # 4. Parse URL. A missing URL is allowed: ``[link]()`` produces a
    # link with an empty href per CommonMark example 485. URL content
    # then gets HTML-entity decoded so ``&auml;`` becomes the literal
    # ``ä`` (which the HTML serialiser percent-encodes as %C3%A4).
    if j < n and text[j] == ")":
        url = ""
    else:
        parsed_url, j = _parse_link_url(text, j)
        if parsed_url is None:
            return None
        url = _decode_entities(parsed_url)
    # 5. Optional title.
    while j < n and text[j] in " \t\n":
        j += 1
    title = ""
    if j < n and text[j] in '"\'(':
        quote = text[j]
        close = ")" if quote == "(" else quote
        j += 1
        title_buf = ""
        while j < n and text[j] != close:
            if (
                text[j] == "\\"
                and j + 1 < n
                and text[j + 1] in _ASCII_PUNCT
            ):
                title_buf += text[j + 1]
                j += 2
                continue
            title_buf += text[j]
            j += 1
        if j >= n or text[j] != close:
            return None
        title = _decode_inline_escapes(title_buf)
        j += 1
    # 6. Skip whitespace before closing ')'.
    while j < n and text[j] in " \t\n":
        j += 1
    if j >= n or text[j] != ")":
        return None
    return text_start, text_end, url, title, j + 1


def _parse_link_url(text: str, start: int) -> tuple[str | None, int]:
    """Parse the URL portion of an inline link. Returns ``(url, next_idx)``.

    Supports the ``<url>`` form (everything until ``>``, where the URL
    body may be empty and ``\\>`` escapes the close-bracket) and the
    bare form (everything until whitespace or ``)``). Backslash escapes
    are recognised only when followed by an ASCII-punctuation
    character; otherwise the backslash is preserved literally per
    CommonMark §2.4.
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
            if (
                text[i] == "\\"
                and i + 1 < n
                and text[i + 1] in _ASCII_PUNCT
            ):
                buf += text[i + 1]
                i += 2
                continue
            buf += text[i]
            i += 1
        if i >= n:
            return None, start
        # Empty <> URL is valid (example 487 produces an empty-href link).
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
        if (
            ch == "\\"
            and i + 1 < n
            and text[i + 1] in _ASCII_PUNCT
        ):
            buf += text[i + 1]
            i += 2
            continue
        buf += ch
        i += 1
    if not buf:
        # Bare-form URL must be non-empty: the bare form has no
        # delimiter to bound an empty URL. Caller can still recover
        # an explicit ``<>`` form above.
        return None, start
    return buf, i


# CommonMark §6.5 autolink scheme regex (simplified): letter then
# 2-31 of letter/digit/plus/dot/dash; or an email-shaped address.
_AUTOLINK_SCHEME = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_AUTOLINK_SCHEME_TAIL = _AUTOLINK_SCHEME + "0123456789+.-"


# HTML tag-name first character: ASCII letter only per CommonMark.
_HTML_TAG_NAME_FIRST = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
# Subsequent tag-name characters: letters, digits, hyphens.
_HTML_TAG_NAME_REST = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
)
# Attribute-name first character: letter, underscore, or colon.
_HTML_ATTR_NAME_FIRST = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_:"
)
# Attribute-name subsequent: letters, digits, hyphens, underscores, colons, dots.
_HTML_ATTR_NAME_REST = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:.-"
)


def _parse_html_open_tag_name(raw: str) -> str | None:
    """Return the lowercase tag name from ``<tag ...>`` / ``<tag/>``.

    None if ``raw`` isn't an open or self-closing tag (i.e. comment,
    CDATA, declaration, PI, close tag).
    """
    if not raw.startswith("<") or len(raw) < 3:
        return None
    if raw[1] in "!?/":
        return None
    j = 1
    while j < len(raw) and raw[j] in _HTML_TAG_NAME_REST:
        j += 1
    return raw[1:j].lower()


def _parse_html_close_tag_name(raw: str) -> str | None:
    """Return the lowercase tag name from ``</tag>``.

    None if ``raw`` is not a close tag.
    """
    if not raw.startswith("</"):
        return None
    j = 2
    while j < len(raw) and raw[j] in _HTML_TAG_NAME_REST:
        j += 1
    return raw[2:j].lower()


def _try_html_tag(text: str, start: int) -> tuple[str, int] | None:
    """Recognise a CommonMark inline-HTML construct at ``text[start:]``.

    Returns (raw_html_substring, end_pos) on a match, where end_pos is
    the index just past the matched substring. Returns None otherwise.

    Recognised shapes (CommonMark 0.31.2 section 6.6):
        <!-- comment -->        — text not containing ``-->`` plus boundary rules
        <![CDATA[ stuff ]]>     — content not containing ``]]>``
        <!DECLARATION ... >     — starts with ``<!`` + ASCII letter
        <? processing ?>        — content not containing ``?>``
        <tagname attrs/>        — open or self-closing
        </tagname>              — close tag

    Distinct from ``_try_autolink`` which handles ``<scheme:...>`` and
    ``<email@host>``. Callers try autolink first; this function is the
    fallback for any other ``<`` that opens a recognised HTML construct.
    """
    n = len(text)
    if start >= n or text[start] != "<":
        return None

    nxt = text[start + 1] if start + 1 < n else ""

    # 1. Comment, CDATA, declaration — all start with `<!`.
    if nxt == "!":
        # CDATA: `<![CDATA[...]]>` (matched before generic declaration
        # because the declaration grammar is letter-first).
        if text.startswith("<![CDATA[", start):
            end = text.find("]]>", start + 9)
            if end != -1:
                return text[start:end + 3], end + 3
            return None
        # Comment: `<!--text-->` where text:
        #   * does not start with ``>`` or ``->``
        #   * does not contain ``--``
        #   * does not end with ``-``
        if text.startswith("<!--", start):
            # Walk forward looking for ``-->``.
            i = start + 4
            # Forbidden start patterns per CommonMark.
            if text[i:i + 1] == ">":
                return None
            if text[i:i + 2] == "->":
                return None
            while i < n - 2:
                if text[i:i + 3] == "-->":
                    return text[start:i + 3], i + 3
                if text[i:i + 2] == "--":
                    # Two consecutive hyphens not part of the closing
                    # marker disqualifies the comment.
                    return None
                i += 1
            return None
        # Declaration: `<!ALPHA ... >` (must have an ASCII letter after `<!`).
        if start + 2 < n and text[start + 2] in _HTML_TAG_NAME_FIRST:
            end = text.find(">", start + 3)
            if end != -1:
                return text[start:end + 1], end + 1
            return None
        return None

    # 2. Processing instruction: `<?...?>` content not containing `?>`.
    if nxt == "?":
        end = text.find("?>", start + 2)
        if end != -1:
            return text[start:end + 2], end + 2
        return None

    # 3. Close tag: `</tagname optional-ws>`
    if nxt == "/":
        if start + 2 >= n or text[start + 2] not in _HTML_TAG_NAME_FIRST:
            return None
        j = start + 3
        while j < n and text[j] in _HTML_TAG_NAME_REST:
            j += 1
        # Optional whitespace then `>`.
        while j < n and text[j] in " \t\n":
            j += 1
        if j < n and text[j] == ">":
            return text[start:j + 1], j + 1
        return None

    # 4. Open tag: `<tagname` attrs `>` or ` />`.
    if nxt in _HTML_TAG_NAME_FIRST:
        j = start + 2
        while j < n and text[j] in _HTML_TAG_NAME_REST:
            j += 1
        # Zero or more attributes.
        while j < n:
            # Required whitespace before each attribute.
            if text[j] not in " \t\n":
                break
            ws_start = j
            while j < n and text[j] in " \t\n":
                j += 1
            # Attribute name?
            if j < n and text[j] in _HTML_ATTR_NAME_FIRST:
                while j < n and text[j] in _HTML_ATTR_NAME_REST:
                    j += 1
                # Optional value: `=value`, `="value"`, or `='value'`.
                k = j
                while k < n and text[k] in " \t\n":
                    k += 1
                if k < n and text[k] == "=":
                    k += 1
                    while k < n and text[k] in " \t\n":
                        k += 1
                    if k >= n:
                        return None
                    if text[k] == '"':
                        close = text.find('"', k + 1)
                        if close == -1:
                            return None
                        j = close + 1
                    elif text[k] == "'":
                        close = text.find("'", k + 1)
                        if close == -1:
                            return None
                        j = close + 1
                    else:
                        # Unquoted value: chars not in space/tab/newline/"/'/=/</>/`.
                        unq_start = k
                        while k < n and text[k] not in " \t\n\"'=<>`":
                            k += 1
                        if k == unq_start:
                            return None
                        j = k
                continue
            # Whitespace not followed by an attribute name — rewind and
            # treat that whitespace as terminator-leading whitespace.
            j = ws_start
            break
        # Optional trailing whitespace.
        while j < n and text[j] in " \t\n":
            j += 1
        # Optional `/` for self-closing.
        if j < n and text[j] == "/":
            j += 1
        if j < n and text[j] == ">":
            return text[start:j + 1], j + 1
        return None

    return None


_AUTOLINK_EMAIL_LOCAL = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    ".!#$%&'*+/=?^_`{|}~-"
)


def _is_valid_autolink_email(s: str) -> bool:
    """Validate the local-part of an email autolink per CommonMark §6.5.

    Allowed chars are ASCII letters, digits, and a specific punctuation
    set (no backslash). The local-part ends at the first ``@``; whatever
    follows must be a domain (we trust the broader scanner that already
    rejected whitespace and ``<``).
    """
    at = s.find("@")
    if at <= 0:
        return False
    local = s[:at]
    return all(c in _AUTOLINK_EMAIL_LOCAL for c in local)


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
        # Try email shape: local@domain.tld. Validate against the
        # CommonMark spec section 6.5 character set (RFC 5322 with a
        # few extensions); backslash, control bytes, and anything
        # outside the allowed punctuation rejects the autolink.
        if "@" in inner and _is_valid_autolink_email(inner):
            return AutoLink(url="mailto:" + inner, text=inner), end + 1
        return None
    scheme = inner[:colon]
    if not scheme or scheme[0] not in _AUTOLINK_SCHEME:
        return None
    if not all(c in _AUTOLINK_SCHEME_TAIL for c in scheme[1:]):
        return None
    if not (2 <= len(scheme) <= 32):
        return None
    return AutoLink(url=inner, text=inner), end + 1


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
    prev_punct = _is_punctuation(prev)
    nxt_punct = _is_punctuation(nxt)

    left_flanking = (not nxt_ws) and (not nxt_punct or prev_ws or prev_punct)
    right_flanking = (not prev_ws) and (not prev_punct or nxt_ws or nxt_punct)

    if ch in "*~":
        # GFM treats `~~` flanking like `*` — no intraword rule.
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
        # For ~ (GFM strikethrough), the opener and closer must have the
        # same length (1 or 2). Skip a mismatched pair the same way we'd
        # skip an unbalanced * or _.
        if d.char == "~":
            if opener.length != d.length:
                # Mismatched tilde lengths cannot close each other in GFM.
                # Treat the closer as not-a-closer and move on.
                if not d.can_open:
                    tokens[i].delim = None
                i += 1
                continue
            eat = d.length
        else:
            eat = 2 if opener.length >= 2 and d.length >= 2 else 1

        # Build the span over tokens (opener_idx, i).
        inner_tokens = tokens[opener_idx + 1:i]
        inner = _emit_inner(inner_tokens)
        if d.char == "~":
            span = Strikethrough(inlines=inner)
        elif eat == 2:
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
        if tok.image is not None:
            flush()
            out.append(tok.image)
            continue
        if tok.html is not None:
            flush()
            out.append(tok.html)
            continue
        if tok.hardbreak:
            flush()
            out.append(HardBreak())
            continue
        if tok.text is not None:
            text_buf += tok.text
            continue

    flush()
    return tuple(out)
