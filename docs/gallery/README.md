# inkmd render gallery

These are *adversarial* sample inputs: markdown chosen to probe
the edges of the parser and layout engine, not to demonstrate
typical use. Each one is the kind of input people throw at a
markdown tool to try to break it.

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
| `07-unicode-winansi.md` | Glyphs at the WinAnsi boundary (currency, accents, dashes, quotes), plus color emoji (flags, skin tones, ZWJ sequences, keycaps) and non-Latin scripts: Cyrillic, Greek, and Latin-Extended render via the embedded font, while a codepoint no font covers (e.g. CJK) shows a visible `[U+XXXX]` marker |
| `08-code-density.md` | Code blocks with extreme indentation, very long lines, mixed languages |
| `09-mid-paragraph-rules.md` | Thematic-break interactions with surrounding content |
| `10-link-edge-cases.md` | Links with brackets in text, parentheses in URLs, nested formatting |

## What's NOT here

This adversarial gallery deliberately stays small and edge-focused.
For supported features shown on *real* documents (images, reference
links, tables, code, emoji rendered in context) see the
[real-world gallery](real-world/README.md), which renders the Ruff
README, a Rust Book chapter, a Simon Willison TIL, and inkmd's own
README. Non-Latin text now renders: Cyrillic, Greek, and
Latin-Extended draw through an embedded font, and a codepoint no
font covers (e.g. CJK, which the bundled font lacks) shows a
visible `[U+XXXX]` marker rather than a silent `?`. The behaviour
is documented in [`docs/conformance.md`](../conformance.md) and the
README, and is visible in `07-unicode-winansi.md` here. This
gallery shows the parser-and-layout edges; the real-world one shows
the happy path.

## What rendering wrong looks like

A failure to render means the PDF is missing content, has
overlapping text, wraps incorrectly, places a code block over a
heading, draws table borders in the wrong place, or otherwise
visually corrupts the document. None of the committed gallery PDFs
do this; if they ever do, treat it as a regression and file an
issue.
