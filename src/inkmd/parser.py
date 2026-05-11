"""Markdown parser.

CommonMark-subset parser, hand-rolled. Two phases:

1. **Block parse**: split input on blank lines into blocks. v0.0.5
   recognises only paragraphs and blank-line separators — headings,
   lists, code blocks, blockquotes, and tables arrive in 0.0.7+.

2. **Inline parse**: walk each block's text and produce inline AST
   nodes. v0.0.6 implements the canonical CommonMark left/right-
   flanking delimiter run algorithm so nested emphasis, underscore
   delimiters, and backslash escapes work correctly.

The two-phase shape is the seam where 0.0.7 will plug in heading and
list recognition without touching the inline parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from inkmd.ast import Code, Document, Emphasis, Inline, Paragraph, Strong, Text


# --- Public entry --------------------------------------------------------


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
    text = text.replace("\x00", "�")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
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

    Exactly one of ``text`` / ``code`` / ``delim`` is set.

    Text and code-span tokens become Text and Code AST nodes verbatim.
    Delimiter tokens may be consumed and replaced with Strong/Emphasis
    spans during resolution, or revert to literal text if unpaired.
    """
    text: str | None = None
    code: str | None = None
    delim: _Delim | None = None


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

        buf += ch
        i += 1

    flush_text()
    return tokens


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

        # Replace the span of tokens (opener_idx .. i inclusive) with:
        # - the opener's remaining delim chars (if any) as literal text
        # - the span node
        # - the closer's remaining delim chars (if any) as literal text
        opener_remainder = opener.char * opener.length
        closer_remainder = d.char * d.length

        new_tokens: list[_Tok] = []
        if opener_remainder:
            new_tokens.append(_Tok(text=opener_remainder))
        new_tokens.append(_Tok(text=None, code=None, delim=None))  # placeholder
        new_tokens[-1].span = span  # type: ignore[attr-defined]
        if closer_remainder:
            new_tokens.append(_Tok(text=closer_remainder))

        # If openers/closers are fully consumed, the delim is gone.
        # Replace tokens[opener_idx .. i+1] with new_tokens.
        tokens[opener_idx:i + 1] = new_tokens
        # Re-walk from just after the new span.
        i = opener_idx + len(new_tokens)


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
        if tok.text is not None:
            text_buf += tok.text
            continue

    flush()
    return tuple(out)
