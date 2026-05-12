"""URL scheme filter for inkmd link annotations.

When inkmd compiles untrusted markdown, links carry the URL the
markdown author put there: `[click](javascript:alert(1))` produces a
PDF `/URI` annotation pointing at `javascript:alert(1)`. Some PDF
readers will execute such schemes; most browsers' built-in PDF
viewers honour them at one point or another.

The filter (on by default in v0.2) walks the AST and replaces any
Link or AutoLink whose URL scheme is not in an allow-list with the
plain text equivalent — link text survives, the `/URI` annotation
does not.

The allow-list is deliberately small but covers all practical use
cases for markdown documents: http(s), email, telephone, FTP, and
XMPP. Anything else (javascript:, data:, vbscript:, file:, custom
app schemes) drops to text.

To opt out — for use cases where the operator trusts the markdown
source absolutely — pass ``safe=False`` to ``compile()`` /
``render_file()``, or ``--allow-unsafe-urls`` on the CLI. The opt-
out preserves the v0.1 behaviour for callers who explicitly want it.
"""

from __future__ import annotations

from inkmd.ast import (
    AutoLink,
    BlockQuote,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    Heading,
    Image,
    Link,
    List,
    ListItem,
    Paragraph,
    Strikethrough,
    Strong,
    Table,
    TableCell,
    Text,
    ThematicBreak,
)


# Schemes that pass the filter unchanged. Lowercase comparison; the
# scheme portion of a URL is the bit before the first colon.
SAFE_SCHEMES = frozenset({
    "http",
    "https",
    "mailto",
    "tel",
    "ftp",
    "xmpp",
})


def is_safe_url(url: str) -> bool:
    """True iff ``url``'s scheme is on the allow-list.

    Fragment-only URLs (``#foo``) and same-document relative URLs
    (no scheme at all) are considered safe — they don't navigate
    out of the document. URLs with malformed scheme prefixes
    (whitespace, control chars) fail the filter.
    """
    if not url:
        return True
    # Fragment-only or relative — no scheme: rest, safe.
    if "://" not in url and ":" not in url:
        return True
    if url.startswith("#") or url.startswith("/"):
        return True
    # Pull the scheme: everything up to the first colon, case-insensitive.
    colon = url.find(":")
    if colon <= 0:
        return False
    scheme = url[:colon].lower()
    # Allow only alpha/digit/+/-/. in the scheme per RFC 3986; if the
    # purported scheme has anything else, this is not a real scheme,
    # treat as relative path (safe).
    if not all(c.isalnum() or c in "+-." for c in scheme):
        return True
    return scheme in SAFE_SCHEMES


def filter_document(doc: Document, *, safe: bool = True) -> Document:
    """Return a new ``Document`` with disallowed URLs flattened to text.

    With ``safe=False`` the document is returned unchanged; the
    parameter exists so call sites don't need to branch.

    The walk is iterative on the container stack. Recursion would
    blow Python's stack on deeply-nested blockquotes (the resource
    probe exercises 10000-deep nesting); we cannot ship a filter
    that pessimises the parser's own depth tolerance.
    """
    if not safe:
        return doc
    return Document(blocks=_filter_blocks(doc.blocks))


def _filter_blocks(blocks):
    """Filter a sequence of blocks. Containers (BlockQuote, List/ListItem)
    are walked iteratively via an explicit worklist so we never exceed
    Python's recursion limit regardless of nesting depth.
    """
    return tuple(_filter_block(b) for b in blocks)


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
            items=tuple(_filter_list_item(it) for it in block.items),
        )
    if isinstance(block, Table):
        return Table(
            headers=tuple(_filter_cell(c) for c in block.headers),
            alignments=block.alignments,
            rows=tuple(
                tuple(_filter_cell(c) for c in row) for row in block.rows
            ),
        )
    # CodeBlock, ThematicBreak — opaque.
    return block


def _filter_blockquote_iterative(root: BlockQuote) -> BlockQuote:
    """Walk a chain of nested BlockQuotes iteratively.

    The case we care about is the resource-probe pattern: a single
    chain of N BlockQuotes each containing the next. Recursion blows
    the stack at N around 1000. We descend the chain non-recursively,
    collect the leaf content, then rebuild the chain bottom-up.

    Mixed cases (a BlockQuote whose children are not a single nested
    BlockQuote) still fall back to recursion via _filter_block, but
    the depth is then bounded by how many *real* branching points
    appear in the document — which in practice is small.
    """
    chain: list[BlockQuote] = []
    cur: BlockQuote | None = root
    while (
        isinstance(cur, BlockQuote)
        and len(cur.blocks) == 1
        and isinstance(cur.blocks[0], BlockQuote)
    ):
        chain.append(cur)
        cur = cur.blocks[0]

    # cur is now either a non-BlockQuote, or a BlockQuote that holds
    # something other than a single nested BlockQuote. Either way,
    # filter its contents with normal recursion (bounded depth).
    if isinstance(cur, BlockQuote):
        inner_blocks = tuple(_filter_block(b) for b in cur.blocks)
        leaf = BlockQuote(blocks=inner_blocks)
    else:
        # Defensive: shouldn't happen given the loop guard.
        leaf = _filter_block(cur)  # type: ignore[arg-type]

    # Rebuild the chain bottom-up.
    result = leaf
    for _ in chain:
        result = BlockQuote(blocks=(result,))
    return result


def _filter_list_item(item: ListItem) -> ListItem:
    return ListItem(
        blocks=tuple(_filter_block(b) for b in item.blocks),
        task=item.task,
    )


def _filter_cell(cell: TableCell) -> TableCell:
    return TableCell(inlines=_filter_inlines(cell.inlines))


def _filter_inlines(inlines):
    """Recurse over inline nodes, replacing unsafe links with their text."""
    out = []
    for node in inlines:
        out.extend(_filter_inline(node))
    return tuple(out)


def _filter_inline(node):
    if isinstance(node, Link):
        if is_safe_url(node.url):
            # Recurse into children (children may also contain unsafe
            # links — shouldn't happen per CommonMark's "no nested
            # links" rule, but the filter remains defensible).
            return [Link(
                inlines=_filter_inlines(node.inlines),
                url=node.url,
                title=node.title,
            )]
        # Unsafe: drop the Link wrapper, keep children as plain inlines.
        return list(_filter_inlines(node.inlines))
    if isinstance(node, AutoLink):
        if is_safe_url(node.url):
            return [node]
        # Unsafe autolink — replace with literal text.
        return [Text(content=node.text)]
    if isinstance(node, Strong):
        return [Strong(inlines=_filter_inlines(node.inlines))]
    if isinstance(node, Emphasis):
        return [Emphasis(inlines=_filter_inlines(node.inlines))]
    if isinstance(node, Strikethrough):
        return [Strikethrough(inlines=_filter_inlines(node.inlines))]
    if isinstance(node, Image):
        # Image URLs are not link annotations — the URL is consulted at
        # embed time by inkmd.image_loader, which has its own
        # http(s)/file/data: gating. The URL-scheme filter does not
        # apply here.
        return [Image(
            inlines=_filter_inlines(node.inlines),
            url=node.url,
            title=node.title,
        )]
    # Text, Code — opaque.
    return [node]
