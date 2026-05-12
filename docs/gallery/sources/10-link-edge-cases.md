# Link edge cases

Links are syntactically simple (`[text](url)`) but the edges are where parsers diverge: brackets in link text, parens in URLs, titles, autolinks, mixing with formatting.

## Title syntax

A link with a title: [click](https://example.com "Tooltip text").

Titles can use single quotes: [click](https://example.com 'Tooltip text').

Or parens: [click](https://example.com (Tooltip text)).

## Brackets in link text

A link with [literal brackets] in the text: [link with \[brackets\] here](https://example.com).

A link containing **bold** and *italic*: [**bold** and *italic*](https://example.com).

A link containing `inline code`: [click for `code`](https://example.com).

## Parens in URL

Standard parens-in-URL: [Wikipedia article](https://en.wikipedia.org/wiki/Markdown_\(markup_language\)).

A URL with multiple parens: [search](https://example.com/path?q=foo\(bar\)baz).

Note: when the URL contains literal parens, the closing one needs to be escaped or the parser will end the URL early. We support both `\(` and `\)`.

## Autolink forms

Angle-bracket autolink: <https://example.com> — URL as both text and target.

Bare autolink (GFM extension): https://example.com — also rendered as a link.

Email autolink (GFM extension): contact@example.com — rendered with `mailto:`.

## Many links in one paragraph

Five [link](https://a.example.com) [tokens](https://b.example.com) [in](https://c.example.com) [one](https://d.example.com) [sentence](https://e.example.com).

## Link without protocol

A bare hostname autolink (GFM extension): www.example.com renders with an implicit `http://`.

A path-only host: example.com/page — should also be detected.

## Link at end of sentence

A link with [punctuation](https://example.com). The trailing period should NOT be part of the URL.

Comma cases: [a](https://example.com), [b](https://example.com), [c](https://example.com).

Question mark and exclamation: see [this](https://example.com)? Or [that](https://example.com)!

## Link in a heading

### Heading with [a link](https://example.com)

Body text follows.

## Link in a list

- [item one with link](https://example.com)
- [item two](https://example.com)
- plain item three
- [item four](https://example.com) with trailing text

## Link in a quote

> A quote with [a link inside](https://example.com).
>
> A second paragraph with [another link](https://example.com).

## Link in a table

| Page | URL |
|------|-----|
| Home | [example.com](https://example.com) |
| Docs | [example.com/docs](https://example.com/docs) |

## Same URL many times

[click](https://example.com) [click](https://example.com) [click](https://example.com) [click](https://example.com) [click](https://example.com)

The PDF should contain five distinct link annotations, each clickable, pointing at the same URL. Deduplication would be a bug (it would make some clicks dead).
