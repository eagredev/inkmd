# inkmd render gallery

These are *adversarial* sample inputs — markdown chosen to probe
the edges of the parser and layout engine, not to demonstrate
typical use. Each one exists because someone on Hacker News or
a similar venue is likely to type something like it into our
tool and screenshot the result.

For each input, the source markdown lives in `sources/`, and
the rendered PDF is committed at the top level of this directory
under the same stem. Re-render any time with:

```sh
for src in docs/gallery/sources/*.md; do
    out="docs/gallery/$(basename "$src" .md).pdf"
    python -m inkmd "$src" -o "$out"
done
```

The PDFs are committed so they can be browsed without running
inkmd. Determinism (same input -> same bytes) means each
committed PDF is exactly reproducible from its source.

## What each input probes

| File | What it stresses |
|------|------------------|
| `01-nested-lists.md` | Lists nested 8 levels deep with mixed marker types |
| `02-long-urls.md` | Single URLs in the 200-, 1000-, and 10000-character range |
| `03-pathological-emphasis.md` | Heavy use of `*` and `_` in adjacent and overlapping patterns |
| `04-table-edges.md` | Wide tables, narrow tables, ragged tables, alignment edge cases |
| `05-mixed-blocks.md` | Tight transitions between paragraph, code, list, quote, table |
| `06-very-long-lines.md` | Single paragraphs of 500-3000 characters per logical line |
| `07-unicode-winansi.md` | Glyphs at the WinAnsi boundary: currency symbols, accented letters, dashes, quotes |
| `08-code-density.md` | Code blocks with extreme indentation, very long lines, mixed languages |
| `09-mid-paragraph-rules.md` | Thematic-break interactions with surrounding content |
| `10-link-edge-cases.md` | Links with brackets in text, parentheses in URLs, nested formatting |

## What's NOT here

Inputs that exercise *unsupported* features (raw HTML, images,
reference links) are not in the gallery because they're already
documented as known limitations in
[`docs/conformance.md`](../conformance.md) and the README. The
gallery shows what we *do*, and how it holds up at the edges.

## What rendering wrong looks like

A failure to render means the PDF is missing content, has
overlapping text, wraps incorrectly, places a code block over a
heading, draws table borders in the wrong place, or otherwise
visually corrupts the document. None of the gallery PDFs in v0.1.0
do this; if they ever do, treat it as a regression and file an
issue.
