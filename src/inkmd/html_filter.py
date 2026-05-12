"""Interpret HtmlInline AST nodes through the Option B allow-list.

The parser preserves every recognised HTML construct as ``HtmlInline``
(literal source bytes). For PDF output we need to decide what each
construct *means* — see docs/design/html-passthrough.md for the full
specification.

Three dispositions per tag:

  * **Promote**: a matched open+close pair around inline content
    becomes a typed inkmd AST node with defined PDF rendering. Examples:
    ``<sub>x</sub>`` -> Subscript(...); ``<a href="...">link</a>`` ->
    Link(...); ``<u>x</u>`` -> Underline(...).
  * **Strip**: a matched open+close pair has its tag syntax removed
    and its enclosed inlines flow through unchanged. Used for tags
    whose visual semantics PDF cannot honour (``<span>``, ``<div>``
    inline, anything not on the allow-list).
  * **Drop**: the tag and everything inside it disappear from the
    output. Used for dangerous constructs (``<script>``, ``<style>``,
    ``<iframe>``, ``<object>``, ``<embed>``, ``<form>``) and comments.

Self-closing tags map to standalone nodes: ``<br>`` -> HardBreak.

Unmatched open or close tags (no partner) drop to literal-text mode,
the same behaviour as the v0.1 escaping when html=False.
"""

from __future__ import annotations

from inkmd.ast import (
    AutoLink,
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
    List,
    ListItem,
    Mark,
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


# Tags that become typed AST nodes. The factory takes a tuple of inline
# children and returns the typed node.
_PROMOTE_TYPED = {
    "sub": Subscript,
    "sup": Superscript,
    "u": Underline,
    "mark": Mark,
    "kbd": Kbd,
    "s": Strikethrough,
    "strike": Strikethrough,
    "del": Strikethrough,
}

# Tags that simply unwrap (keep children, drop tags).
_PROMOTE_UNWRAP = {
    "span",
    "div",
    "p",
    "em",
    "i",
    "strong",
    "b",
    "small",
    "big",
    "tt",
    "code",
    "cite",
    "abbr",
    "dfn",
    "q",
    "var",
    "samp",
    "ins",
    "summary",
    "details",
    "section",
    "article",
    "aside",
    "header",
    "footer",
    "nav",
    "figure",
    "figcaption",
}

# Tags whose content is also dropped (security/scope reasons).
_DROP_WITH_CONTENT = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "select",
    "option",
    "textarea",
    "noscript",
    "frame",
    "frameset",
    "applet",
    "video",
    "audio",
    "source",
    "track",
    "canvas",
    "svg",
    "math",
    "link",
    "meta",
    "base",
    "title",
    "head",
}

# Self-closing tags handled as standalone nodes.
_SELF_CLOSING = {
    "br": lambda attrs: HardBreak(),
    "hr": lambda attrs: HardBreak(),  # in inline context, treat as a break.
    "wbr": lambda attrs: HardBreak(),
}


def filter_document(doc: Document, *, html: bool = True) -> Document:
    """Walk ``doc`` and apply the HTML allow-list to every paragraph's
    inline content. With ``html=False`` returns ``doc`` unchanged
    (callers handle the no-html mode by escaping at parse time)."""
    if not html:
        return doc
    return Document(blocks=tuple(_filter_block(b) for b in doc.blocks))


def _filter_block(block):
    if isinstance(block, Paragraph):
        return Paragraph(inlines=_filter_inlines(block.inlines))
    if isinstance(block, Heading):
        return Heading(level=block.level, inlines=_filter_inlines(block.inlines))
    if isinstance(block, BlockQuote):
        return _filter_blockquote_iterative(block)
    if isinstance(block, List):
        return List(
            ordered=block.ordered,
            start=block.start,
            tight=block.tight,
            items=tuple(
                ListItem(
                    blocks=tuple(_filter_block(b) for b in it.blocks),
                    task=it.task,
                )
                for it in block.items
            ),
        )
    if isinstance(block, Table):
        return Table(
            headers=tuple(
                TableCell(inlines=_filter_inlines(c.inlines)) for c in block.headers
            ),
            alignments=block.alignments,
            rows=tuple(
                tuple(TableCell(inlines=_filter_inlines(c.inlines)) for c in row)
                for row in block.rows
            ),
        )
    return block


def _filter_blockquote_iterative(root: BlockQuote) -> BlockQuote:
    """Same iterative pattern as url_filter / image_loader for deeply
    nested single-child blockquote chains."""
    chain: list[BlockQuote] = []
    cur = root
    while (
        isinstance(cur, BlockQuote)
        and len(cur.blocks) == 1
        and isinstance(cur.blocks[0], BlockQuote)
    ):
        chain.append(cur)
        cur = cur.blocks[0]
    if isinstance(cur, BlockQuote):
        leaf = BlockQuote(blocks=tuple(_filter_block(b) for b in cur.blocks))
    else:
        leaf = _filter_block(cur)  # type: ignore[arg-type]
    result = leaf
    for _ in chain:
        result = BlockQuote(blocks=(result,))
    return result


def _filter_inlines(inlines: tuple[Inline, ...]) -> tuple[Inline, ...]:
    """Apply the HTML allow-list to a flat sequence of inlines.

    The algorithm scans for HtmlInline tokens; matched open/close pairs
    rewrap inner content into typed AST nodes (Subscript, Kbd, etc.) or
    flatten with the tag stripped. Unmatched tokens drop entirely
    (literal text falls back to the surrounding Text nodes).

    Recurses into the children of Strong, Emphasis, Strikethrough, Link
    and Image-alt content so nested HTML in those contexts is also
    handled.
    """
    # First recurse into inline containers (they may themselves contain
    # HtmlInline nodes that need processing).
    pre_processed: list[Inline] = []
    for n in inlines:
        if isinstance(n, Strong):
            pre_processed.append(Strong(inlines=_filter_inlines(n.inlines)))
        elif isinstance(n, Emphasis):
            pre_processed.append(Emphasis(inlines=_filter_inlines(n.inlines)))
        elif isinstance(n, Strikethrough):
            pre_processed.append(Strikethrough(inlines=_filter_inlines(n.inlines)))
        elif isinstance(n, Link):
            pre_processed.append(Link(
                inlines=_filter_inlines(n.inlines),
                url=n.url,
                title=n.title,
            ))
        elif isinstance(n, Image):
            pre_processed.append(Image(
                inlines=_filter_inlines(n.inlines),
                url=n.url,
                title=n.title,
                resolved=n.resolved,
            ))
        elif (
            isinstance(n, (Subscript, Superscript, Underline, Mark, Kbd))
        ):
            cls = type(n)
            pre_processed.append(cls(inlines=_filter_inlines(n.inlines)))
        else:
            pre_processed.append(n)

    # Now scan for HtmlInline tokens and apply the allow-list.
    return _scan_html(pre_processed)


def _scan_html(inlines: list[Inline]) -> tuple[Inline, ...]:
    """Walk left-to-right; consume HtmlInline tokens with allow-list rules.

    Pairs an open tag with the nearest following compatible close tag,
    wrapping the inlines between them in the corresponding typed node.
    """
    out: list[Inline] = []
    i = 0
    n = len(inlines)
    while i < n:
        node = inlines[i]
        if not isinstance(node, HtmlInline):
            out.append(node)
            i += 1
            continue

        raw = node.raw

        # Comments, CDATA, declarations, PIs — drop entirely.
        if raw.startswith("<!--") or raw.startswith("<![CDATA[") or raw.startswith("<?") or (
            raw.startswith("<!") and not raw.startswith("<!--")
        ):
            i += 1
            continue

        # Close tag with no matching open is a stray; drop.
        if raw.startswith("</"):
            i += 1
            continue

        # Open tag. Parse name + decide disposition.
        tag = _open_tag_name(raw)
        attrs = _open_tag_attrs(raw)
        self_closing = raw.endswith("/>")

        # Self-closing standalone tags first.
        if tag in _SELF_CLOSING:
            out.append(_SELF_CLOSING[tag](attrs))
            i += 1
            continue

        # `<br>` without the slash (HTML5 also accepts this).
        if self_closing or tag in ("br", "hr", "wbr"):
            if tag in _SELF_CLOSING:
                out.append(_SELF_CLOSING[tag](attrs))
            i += 1
            continue

        # Drop-with-content tags: skip everything until the matching close.
        if tag in _DROP_WITH_CONTENT:
            end = _find_matching_close(inlines, i, tag)
            i = (end + 1) if end is not None else (i + 1)
            continue

        # `<a href=...>...</a>` -> Link.
        if tag == "a":
            end = _find_matching_close(inlines, i, tag)
            if end is None:
                # Unmatched open; drop tag syntax, keep nothing extra.
                i += 1
                continue
            inner = _scan_html(inlines[i + 1:end])
            href = attrs.get("href", "")
            title = attrs.get("title", "")
            if href:
                out.append(Link(inlines=inner, url=href, title=title))
            else:
                # No href: this is a `<a name="anchor">` or similar.
                # Flatten the content; PDF named destinations are a
                # future enhancement.
                out.extend(inner)
            i = end + 1
            continue

        # Typed promotion (sub, sup, u, mark, kbd, s, strike, del).
        if tag in _PROMOTE_TYPED:
            end = _find_matching_close(inlines, i, tag)
            if end is None:
                # Unmatched open; drop the tag syntax.
                i += 1
                continue
            inner = _scan_html(inlines[i + 1:end])
            out.append(_PROMOTE_TYPED[tag](inlines=inner))
            i = end + 1
            continue

        # Unwrap promotion: drop the tag, keep children.
        if tag in _PROMOTE_UNWRAP:
            end = _find_matching_close(inlines, i, tag)
            if end is None:
                # Unmatched open; drop the tag syntax.
                i += 1
                continue
            inner = _scan_html(inlines[i + 1:end])
            out.extend(inner)
            i = end + 1
            continue

        # Unknown tag: drop the tag syntax. If there is a matching
        # close, drop that too; keep the children in between.
        end = _find_matching_close(inlines, i, tag)
        if end is None:
            i += 1
            continue
        inner = _scan_html(inlines[i + 1:end])
        out.extend(inner)
        i = end + 1

    return tuple(out)


def _open_tag_name(raw: str) -> str:
    """Extract the lowercase tag name from an HTML open tag string."""
    # ``<tagname...`` -> tagname
    i = 1
    while i < len(raw) and (raw[i].isalnum() or raw[i] == "-"):
        i += 1
    return raw[1:i].lower()


def _close_tag_name(raw: str) -> str:
    """Extract the lowercase tag name from an HTML close tag string."""
    i = 2
    while i < len(raw) and (raw[i].isalnum() or raw[i] == "-"):
        i += 1
    return raw[2:i].lower()


def _open_tag_attrs(raw: str) -> dict[str, str]:
    """Parse name=value pairs from an HTML open tag. Loose but adequate
    for the small set of attributes we honour (href, title, name)."""
    attrs: dict[str, str] = {}
    # Strip ``<tagname`` prefix and the trailing ``/>`` or ``>``.
    tag_end = 1
    while tag_end < len(raw) and (raw[tag_end].isalnum() or raw[tag_end] == "-"):
        tag_end += 1
    body = raw[tag_end:].rstrip(">").rstrip("/").strip()

    i = 0
    n = len(body)
    while i < n:
        # Skip whitespace.
        while i < n and body[i] in " \t\n":
            i += 1
        if i >= n:
            break
        # Attribute name.
        name_start = i
        while i < n and (body[i].isalnum() or body[i] in "-_:."):
            i += 1
        if i == name_start:
            break
        name = body[name_start:i].lower()
        # Optional `=value` clause.
        while i < n and body[i] in " \t\n":
            i += 1
        if i < n and body[i] == "=":
            i += 1
            while i < n and body[i] in " \t\n":
                i += 1
            if i < n and body[i] in "\"'":
                quote = body[i]
                i += 1
                vstart = i
                while i < n and body[i] != quote:
                    i += 1
                attrs[name] = body[vstart:i]
                i += 1
            else:
                vstart = i
                while i < n and body[i] not in " \t\n":
                    i += 1
                attrs[name] = body[vstart:i]
        else:
            attrs[name] = ""
    return attrs


def _find_matching_close(inlines: list[Inline], start: int, tag: str) -> int | None:
    """Find the index of the matching close tag for the open tag at
    ``start``. Handles nesting (an inner ``<a>...</a>`` doesn't close
    the outer one). Returns None if no matching close exists."""
    depth = 1
    i = start + 1
    while i < len(inlines):
        n = inlines[i]
        if isinstance(n, HtmlInline):
            raw = n.raw
            if raw.startswith("</"):
                close_tag = _close_tag_name(raw)
                if close_tag == tag:
                    depth -= 1
                    if depth == 0:
                        return i
            elif not (
                raw.startswith("<!") or raw.startswith("<?") or raw.endswith("/>")
            ):
                open_tag = _open_tag_name(raw)
                if open_tag == tag:
                    depth += 1
        i += 1
    return None
