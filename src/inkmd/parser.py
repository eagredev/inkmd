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

from inkmd.ast import Code, Document, Emphasis, Inline, Paragraph, Strong, Text


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

    v0.0.5 recognises three inline constructs:
      - ``**...**`` → ``Strong``  (asterisks only; underscore deferred)
      - ``*...*``   → ``Emphasis``
      - ``` `...` ``` → ``Code``    (no nested parsing inside)

    Everything else accumulates into ``Text`` nodes. Unmatched
    delimiters fall back to literal text — ``"**not closed"`` produces
    ``Text("**not closed")`` rather than an error.

    KNOWN LIMITATIONS (v0.0.5):
      - Nested same-type emphasis is not handled correctly. Input like
        ``**bold *italic***`` exits the Strong span at the first ``**``
        which falls inside the ``***`` run, leaving a stray ``*`` and
        the italic text un-emphasised. Real CommonMark requires the
        left/right-flanking delimiter algorithm; that lands in 0.0.6.
      - Underscore delimiters (``__bold__``, ``_italic_``) are not
        recognised; the underscore characters appear literally. Defer
        to 0.0.6.
      - Escaped delimiters (``\\*not emphasised\\*``) are not handled;
        the backslashes appear literally. Defer to 0.0.6.

    The strategy is a single linear scan with a small lookahead: at
    each position we test for a delimiter that has a matching closer
    later in the string; if so we consume the span; otherwise we
    accumulate the current char into a pending text buffer.
    """
    if not text:
        return ()

    out: list[Inline] = []
    buf = ""  # pending plain text
    i = 0
    n = len(text)

    def flush_text() -> None:
        nonlocal buf
        if buf:
            out.append(Text(content=buf))
            buf = ""

    while i < n:
        # Inline code: backtick to next backtick. Content is opaque.
        if text[i] == "`":
            close = text.find("`", i + 1)
            if close != -1:
                flush_text()
                out.append(Code(content=text[i + 1:close]))
                i = close + 1
                continue

        # Strong: ** ... **
        if text.startswith("**", i):
            close = _find_close(text, i + 2, "**")
            if close != -1:
                flush_text()
                inner = _parse_inlines(text[i + 2:close])
                out.append(Strong(inlines=inner))
                i = close + 2
                continue

        # Emphasis: * ... *  (single asterisk, NOT part of a ** pair)
        # The ** branch above already tried and failed; if text[i:i+2] is
        # "**" we must not also treat text[i] as a standalone Emphasis
        # opener, otherwise "**unclosed" would parse as Emphasis("")
        # plus stray text.
        if text[i] == "*" and not (i + 1 < n and text[i + 1] == "*"):
            close = _find_close_single_star(text, i + 1)
            if close != -1:
                flush_text()
                inner = _parse_inlines(text[i + 1:close])
                out.append(Emphasis(inlines=inner))
                i = close + 1
                continue

        buf += text[i]
        i += 1

    flush_text()
    return tuple(out)


def _find_close(text: str, start: int, delim: str) -> int:
    """Find the next occurrence of ``delim`` at or after ``start``.

    Returns -1 if none. Used for fixed-length delimiters like ``**``.
    """
    idx = text.find(delim, start)
    return idx


def _find_close_single_star(text: str, start: int) -> int:
    """Find the next single ``*`` that is NOT part of a ``**``.

    This is the v0.0.5 simplification of CommonMark's emphasis rules:
    we only treat a lone ``*`` as a closing emphasis delimiter. A run
    of two or more asterisks is reserved for Strong. Returns -1 if no
    such position exists.
    """
    i = start
    n = len(text)
    while i < n:
        if text[i] == "*":
            # Not a closer if it's the first of a "**" pair.
            if i + 1 < n and text[i + 1] == "*":
                i += 2
                continue
            return i
        i += 1
    return -1
