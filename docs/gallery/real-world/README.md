# Real-world rendering gallery

Four real third-party documents plus one constructed feature
showcase, rendered through inkmd as-is, with honest notes about what
worked and what did not.

The [`docs/gallery/`](..) directory one level up contains
spec-edge-case verification PDFs: documents specifically constructed
to exercise tricky CommonMark or GFM rules. This `real-world/`
directory is the opposite: documents that real authors wrote for
real audiences, rendered through inkmd to show what a visitor would
get if they pointed the tool at a document from their own life.

## The documents

| Document | Source | Pages | Notes |
|----------|--------|-------|-------|
| [Simon Willison TIL](simonw-til/) | `simonw/til` | 4 | Clean render; longform blog post with code blocks |
| [Rust Book §1.3 "Hello, Cargo!"](rust-book-ch1-3-hello-cargo/) | `rust-lang/book` | 5 | Clean render; multi-page technical book chapter |
| [inkmd's own README](inkmd-self-render/) | This repo | 14 | Dogfood; the centred `<p align><img>` hero renders, image embedded |
| [Ruff README](ruff-readme/) | `astral-sh/ruff` | 11 | Mixed; color emoji render, SVG badges fall back to alt-text |
| [Non-Latin scripts](nonlatin-scripts/) | Constructed showcase | 2 | Non-Latin scripts: Cyrillic, Greek, and Latin-Extended render via the embedded font; unsupported codepoints (e.g. CJK) show a visible `[U+XXXX]` marker. Table cells still render `?` (known limitation) |

Each subdirectory contains:

- `source.md`: the exact markdown that was rendered
- `output.pdf`: the PDF inkmd produced
- `README.md`: what the document is, where it came from, and what
  to look at (including any rendering limitations)

## How these were rendered

All were compiled with:

```python
inkmd.compile(
    source_text,
    page_size="letter",
    family="helvetica",
    allow_remote_images=True,
    base_dir=document_directory,
)
```

`allow_remote_images=True` was set so that any HTTP image references
would be fetched at compile time rather than falling back to alt
text. In practice this only affected the Ruff README, where the
shields.io badges (all SVG) still fell back to alt text because
inkmd supports PNG and JPEG image formats only.

The render is reproducible: see `scripts/render_gallery.py` to
re-run.

## Why this gallery exists

This gallery shows what inkmd produces on documents real authors
wrote for real audiences, not a curated demo: the README of a
known project, a chapter of a book, a blog post in a recognisable
style. Those documents cover those shapes; the non-Latin showcase
adds a direct look at the v0.4 font-embedding feature on text the
base fonts cannot draw. The README for each one is candid about
what fell short.
