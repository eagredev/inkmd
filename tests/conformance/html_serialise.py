"""Serialise inkmd's AST to CommonMark reference-HTML output.

The CommonMark spec test suite compares byte-for-byte HTML against
expected output. We don't ship an HTML renderer in the public API
(inkmd's job is PDFs), but we need one for conformance testing.

This serialiser produces output formatted to match CommonMark 0.31.2
reference output conventions:
- Block elements followed by '\\n'
- Tight lists use <li>content</li>, loose lists use <li>\\n<p>content</p>\\n</li>
- Code blocks: <pre><code>...</code></pre> with trailing newline inside the code
- Info string after the fence becomes a class attribute on <code>
- HTML entity escaping for &, <, >, " in text nodes; URL percent-escaping
  for link destinations follows the spec's loose URL handling
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
    Text,
    ThematicBreak,
    Underline,
)


def escape_html(text: str) -> str:
    """Escape & < > " for HTML attribute and text content.

    The CommonMark reference renderer escapes these four characters
    everywhere in text and attributes. Single quotes are not escaped.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# URL characters that are NOT percent-encoded by the CommonMark reference
# renderer. See https://spec.commonmark.org/0.31.2/#example-498 for the
# canonical example: most ASCII printables pass through, but ` ` and a
# few others get encoded.
_URL_SAFE = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    "-._~:/?#@!$&'()*+,;=%"
)


def escape_url(url: str) -> str:
    """URL-escape per the CommonMark reference renderer.

    The spec's reference renderer percent-encodes characters that aren't
    in a small allow-list. It also re-escapes existing % sequences only
    when they don't already look like a valid escape.
    """
    out: list[str] = []
    i = 0
    while i < len(url):
        c = url[i]
        if c == "%":
            # Preserve an already-valid escape; otherwise escape the %.
            if i + 2 < len(url) and _is_hex(url[i + 1]) and _is_hex(url[i + 2]):
                out.append(c)
            else:
                out.append("%25")
        elif c in _URL_SAFE:
            out.append(c)
        elif ord(c) < 128:
            out.append(f"%{ord(c):02X}")
        else:
            for byte in c.encode("utf-8"):
                out.append(f"%{byte:02X}")
        i += 1
    # The CommonMark reference also HTML-escapes the resulting URL.
    return escape_html("".join(out))


def _is_hex(c: str) -> bool:
    return c in "0123456789abcdefABCDEF"


def _strip_softbreak_whitespace(s: str) -> str:
    """Strip whitespace adjacent to soft-break newlines per CommonMark.

    Per spec section 6.8, a soft line break ``trims any preceding or
    following spaces / tabs`` when rendering. Hard breaks are emitted
    as <br /> AST nodes earlier, so any remaining newlines in Text
    content come from soft breaks and should have their surrounding
    horizontal whitespace stripped.
    """
    lines = s.split("\n")
    if len(lines) == 1:
        return s
    cleaned = [lines[0].rstrip(" \t")]
    cleaned.extend(line.lstrip(" \t").rstrip(" \t") for line in lines[1:-1])
    cleaned.append(lines[-1].lstrip(" \t"))
    return "\n".join(cleaned)


def render_inline(node) -> str:
    """Serialise one inline node to HTML."""
    if isinstance(node, Text):
        return escape_html(_strip_softbreak_whitespace(node.content))
    if isinstance(node, Strong):
        return f"<strong>{render_inlines(node.inlines)}</strong>"
    if isinstance(node, Emphasis):
        return f"<em>{render_inlines(node.inlines)}</em>"
    if isinstance(node, Strikethrough):
        # GFM extension; not in CommonMark proper.
        return f"<del>{render_inlines(node.inlines)}</del>"
    if isinstance(node, Code):
        return f"<code>{escape_html(node.content)}</code>"
    if isinstance(node, Link):
        title_attr = f' title="{escape_html(node.title)}"' if node.title else ""
        return (
            f'<a href="{escape_url(node.url)}"{title_attr}>'
            f"{render_inlines(node.inlines)}</a>"
        )
    if isinstance(node, AutoLink):
        return f'<a href="{escape_url(node.url)}">{escape_html(node.text)}</a>'
    if isinstance(node, Image):
        # CommonMark §6.4: <img src="URL" alt="ALT" title="TITLE">.
        # Alt is the text-content of the alt inlines (formatting flat-
        # tened); the spec reference renderer recursively flattens
        # link/emphasis structure inside alt down to plain text.
        alt = _inlines_to_alt_text(node.inlines)
        title_attr = f' title="{escape_html(node.title)}"' if node.title else ""
        return (
            f'<img src="{escape_url(node.url)}" alt="{escape_html(alt)}"'
            f"{title_attr} />"
        )
    if isinstance(node, HtmlInline):
        # CommonMark passes inline HTML through verbatim. Each
        # recognised HTML construct emits the literal source bytes.
        return node.raw
    if isinstance(node, HardBreak):
        # CommonMark reference renderer emits "<br />\n" so the next
        # piece of content appears on its own source line. Conformance
        # tests compare byte-for-byte.
        return "<br />\n"
    if isinstance(node, Subscript):
        return f"<sub>{render_inlines(node.inlines)}</sub>"
    if isinstance(node, Superscript):
        return f"<sup>{render_inlines(node.inlines)}</sup>"
    if isinstance(node, Underline):
        return f"<u>{render_inlines(node.inlines)}</u>"
    if isinstance(node, Mark):
        return f"<mark>{render_inlines(node.inlines)}</mark>"
    if isinstance(node, Kbd):
        return f"<kbd>{render_inlines(node.inlines)}</kbd>"
    raise TypeError(f"unknown inline node: {type(node).__name__}")


def _inlines_to_alt_text(nodes) -> str:
    """Flatten an inline tree to its plain-text alt content.

    Per CommonMark §6.4, alt text is "the textual content of the inner
    inlines". Emphasis / strong / code spans / links contribute their
    text content only; the surrounding markup is stripped. Nested
    images contribute their alt text recursively.
    """
    out = []
    for n in nodes:
        if isinstance(n, Text):
            out.append(n.content)
        elif isinstance(n, Code):
            out.append(n.content)
        elif isinstance(n, AutoLink):
            out.append(n.text)
        elif isinstance(n, (Strong, Emphasis, Strikethrough, Link)):
            out.append(_inlines_to_alt_text(n.inlines))
        elif isinstance(n, Image):
            out.append(_inlines_to_alt_text(n.inlines))
    return "".join(out)


def render_inlines(nodes) -> str:
    return "".join(render_inline(n) for n in nodes)


def render_block(node) -> str:
    """Serialise one block node to HTML. Returns the block's HTML with
    its trailing newline (per CommonMark reference output style)."""
    if isinstance(node, Paragraph):
        return f"<p>{render_inlines(node.inlines)}</p>\n"
    if isinstance(node, Heading):
        return f"<h{node.level}>{render_inlines(node.inlines)}</h{node.level}>\n"
    if isinstance(node, ThematicBreak):
        return "<hr />\n"
    if isinstance(node, CodeBlock):
        if node.info:
            # Take only the first whitespace-separated token as the lang.
            lang = node.info.split()[0] if node.info.split() else ""
            class_attr = f' class="language-{escape_html(lang)}"' if lang else ""
        else:
            class_attr = ""
        body = escape_html(node.content)
        if body and not body.endswith("\n"):
            body += "\n"
        return f"<pre><code{class_attr}>{body}</code></pre>\n"
    if isinstance(node, BlockQuote):
        inner = "".join(render_block(b) for b in node.blocks)
        return f"<blockquote>\n{inner}</blockquote>\n"
    if isinstance(node, List):
        tag = "ol" if node.ordered else "ul"
        start_attr = f' start="{node.start}"' if node.ordered and node.start != 1 else ""
        items_html: list[str] = []
        for item in node.items:
            items_html.append(_render_list_item(item, node.tight))
        return f"<{tag}{start_attr}>\n" + "".join(items_html) + f"</{tag}>\n"
    if isinstance(node, Table):
        # GFM extension; not in CommonMark proper.
        return _render_table(node)
    raise TypeError(f"unknown block node: {type(node).__name__}")


def _task_checkbox(item: ListItem) -> str:
    """Return the GFM task-list checkbox HTML for this item, or empty."""
    if item.task is None:
        return ""
    if item.task:
        return '<input checked="" disabled="" type="checkbox"> '
    return '<input disabled="" type="checkbox"> '


def _render_list_item(item: ListItem, tight: bool) -> str:
    """Render one list item per CommonMark tight/loose rules."""
    if not item.blocks:
        return "<li></li>\n"

    checkbox = _task_checkbox(item)

    if tight:
        # Tight: strip the <p> wrapper from any contained Paragraph.
        parts: list[str] = []
        for b in item.blocks:
            if isinstance(b, Paragraph):
                parts.append(render_inlines(b.inlines))
            else:
                # Nested non-paragraph block within a tight item.
                # The CommonMark reference renders nested lists indented;
                # we emit the block's full HTML on its own line, surrounded
                # by newlines, to match the reference output shape.
                parts.append("\n" + render_block(b).rstrip("\n") + "\n")
        body = "".join(parts)
        return f"<li>{checkbox}{body}</li>\n"
    else:
        # Loose: keep <p> wrappers, blocks on their own lines.
        # GFM places the checkbox INSIDE the first <p>, before its content.
        if checkbox and isinstance(item.blocks[0], Paragraph):
            first = item.blocks[0]
            first_html = (
                f"<p>{checkbox}{render_inlines(first.inlines)}</p>\n"
            )
            rest = "".join(render_block(b) for b in item.blocks[1:])
            return f"<li>\n{first_html}{rest}</li>\n"
        inner = "".join(render_block(b) for b in item.blocks)
        return f"<li>\n{inner}</li>\n"


def _render_table(table: Table) -> str:
    """Render a GFM table — GFM extension format."""
    lines = ["<table>"]
    lines.append("<thead>")
    lines.append("<tr>")
    for cell, align in zip(table.headers, table.alignments):
        attr = f' align="{align}"' if align else ""
        lines.append(f"<th{attr}>{render_inlines(cell.inlines)}</th>")
    lines.append("</tr>")
    lines.append("</thead>")
    if table.rows:
        lines.append("<tbody>")
        for row in table.rows:
            lines.append("<tr>")
            for cell, align in zip(row, table.alignments):
                attr = f' align="{align}"' if align else ""
                lines.append(f"<td{attr}>{render_inlines(cell.inlines)}</td>")
            lines.append("</tr>")
        lines.append("</tbody>")
    lines.append("</table>")
    return "\n".join(lines) + "\n"


def render_document(doc: Document) -> str:
    """Serialise a Document to HTML matching CommonMark reference style."""
    return "".join(render_block(b) for b in doc.blocks)
