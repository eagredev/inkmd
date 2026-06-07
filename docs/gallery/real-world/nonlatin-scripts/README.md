# Non-Latin scripts

A constructed showcase of v0.4's headline feature: rendering text the 14 base PDF fonts cannot represent.

## What it is

`source.md` is a short multi-script document, not a third-party README. It exists to show, in one place, exactly what each of inkmd's text paths produces:

- Cyrillic, Greek, and Latin-Extended (Russian, Ukrainian, Greek, Polish, Czech, Turkish, Vietnamese) render as real glyphs through the bundled DejaVuSans embedded font. The text is selectable and copyable from the PDF.
- CJK (Japanese, Chinese, Korean) shows a visible `[U+XXXX]` marker for each codepoint, because the bundled font has no CJK glyphs. inkmd also emits one `MissingGlyphWarning` per compile naming the missing codepoints. CJK full rendering is a planned later font pack.
- A mixed line shows the per-codepoint split: English stays on the base-14 font, Cyrillic and Greek route to the embedded font, and CJK falls to the marker, all on one line.

## What to look at

In `output.pdf`:

- The Cyrillic, Greek, and Latin-Extended lines render correctly. Compare against the source to confirm every accented letter is present.
- The CJK lines show `[U+XXXX]` markers, not blank space and not `?`. The visible, labelled marker is the feature: a reader can see precisely which codepoints have no glyph, rather than silently losing them.
- Non-Latin text inside the table cells still renders `?`. Embedded-font routing does not yet reach table cells (column widths are computed before the run split); that is a known limitation with a fix pending. The same text in prose renders through the embedded font.

## How it was rendered

Compiled the same way as the other exhibits, via `scripts/render_gallery.py`:

```python
inkmd.compile(
    source_text,
    page_size="letter",
    family="helvetica",
    allow_remote_images=True,
    base_dir=document_directory,
)
```

It uses no images, so the render is fully offline and deterministic.
