# Real-world rendering gallery

Four real third-party documents, rendered through inkmd as-is, with
honest notes about what worked and what did not.

The [`docs/gallery/`](..) directory one level up contains
spec-edge-case verification PDFs — documents specifically constructed
to exercise tricky CommonMark or GFM rules. This `real-world/`
directory is the opposite: documents that real authors wrote for
real audiences, rendered through inkmd to show what a visitor would
get if they pointed the tool at a document from their own life.

## The four documents

| Document | Source | Pages | Notes |
|----------|--------|-------|-------|
| [Simon Willison TIL](simonw-til/) | `simonw/til` | 4 | Clean render; longform blog post with code blocks |
| [Rust Book §1.3 "Hello, Cargo!"](rust-book-ch1-3-hello-cargo/) | `rust-lang/book` | 5 | Clean render; multi-page technical book chapter |
| [inkmd's own README](inkmd-self-render/) | This repo | 9 | Dogfood; missing hero image (HTML `<p><img>` not supported in v0.2) |
| [Ruff README](ruff-readme/) | `astral-sh/ruff` | 11 | Mixed; emojis render as `?` and SVG badges as alt-text |

Each subdirectory contains:

- `source.md` — the exact markdown that was rendered
- `output.pdf` — the PDF inkmd produced
- `README.md` — what the document is, where it came from, and what
  to look at (including any rendering limitations)

## How these were rendered

All four were compiled with:

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
inkmd v0.2 supports PNG and JPEG image formats only.

The render is reproducible: see `scripts/render_gallery.py` to
re-run.

## Why this gallery exists

A reader who is considering inkmd does not want a curated demo. They
want to know what the tool produces on documents from their own
experience: the README of a project they know, a chapter of a book
they have read, a blog post in a style they recognise. The four
documents here cover those shapes. The READMEs for each one are
candid about what fell short, because the point of a real-world
gallery is not to win every comparison but to let the reader see
the tool's actual posture before they install it.
