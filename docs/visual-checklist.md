# Visual checklist

Automated tests verify *bytes on the page*, not *what humans see*. They are necessary but insufficient for a rendering tool. Every milestone produces a sample PDF; this file lists what to look for when opening it in a real viewer.

The discipline:

1. After each milestone, run the sample-generation script (see "How to regenerate").
2. Open the resulting PDF in a viewer (Okular, Evince, macOS Preview, Adobe Reader, Chrome — ideally at least two of these).
3. Walk the relevant checklist below. Each item is a yes/no question.
4. If any item is "no" → file the bug, don't ship.
5. If the checklist itself is missing a category for a regression that occurred → add the category before continuing.

## Why this exists

Background: in milestone 0.0.3, the em dash rendered as a blank glyph because the font dictionary didn't declare `/Encoding /WinAnsiEncoding`. `qpdf --check` passed. `pdftotext` extracted the bytes correctly. The fault only surfaced when a human opened the PDF and noticed the missing dash. **The lesson:** byte-level tools agree with each other about what's on the page, not with humans about what's visible.

A `pdftoppm`-based rasterising test could automate some of this in future, but the cost of building it well is high and the cost of an opened-the-PDF-and-looked check is ~30 seconds per milestone. We keep this manual until the project ships v0.1.

## Per-milestone checklists

### Milestone 0.0.1 — hello-world PDF

Sample: `/tmp/hello.pdf` from running

```python
from inkmd.pdf import hello_world_pdf
open('/tmp/hello.pdf','wb').write(hello_world_pdf())
```

- [ ] File opens in a PDF viewer (no error dialog).
- [ ] Exactly one page.
- [ ] Page size is Letter (8.5 × 11 inch / 612 × 792 pt).
- [ ] Text "Hello, world!" appears on the page.
- [ ] Text is in **Helvetica** (sans-serif), 12 pt.
- [ ] Text is positioned near the top-left, roughly 1 inch in from each edge.
- [ ] Nothing else on the page.

### Milestone 0.0.2 — multi-line, multi-page plain text

Sample: `/tmp/multi.pdf` (see `tests/test_text_pdf.py` for the input; or use a paragraph-rich blob).

- [ ] File opens; reports correct page count (≥ 2 for sample inputs designed to overflow one page).
- [ ] Paragraphs visibly separated by blank space (the 6pt paragraph spacing).
- [ ] Lines wrap at the right margin — no text spilling into the right edge.
- [ ] Line spacing looks comfortable (14.4 pt leading at 12 pt body).
- [ ] No words cut off by a page break (paragraphs may split across pages, individual lines must not).
- [ ] Top and bottom margins look symmetric (1 inch).
- [ ] Last page may be partially blank (expected) but not empty.

### Milestone 0.0.3.1 — kerning

After milestone 0.0.3, kerning pair adjustments are applied to consecutive glyphs in the same font. Inspect any styled sample PDF and look at:

- [ ] **"We", "Wo", "Va", "To", "Te", "Ya"** and similar capital-then-lowercase pairs: glyphs should sit visibly closer than they would without kerning, but not overlap. Compare to a screenshot from before 0.0.3.1 if available.
- [ ] **Within a single word**, no glyphs overlap.
- [ ] **Across font boundaries** (regular → bold, body → code), spacing looks natural — kerning does not apply across font switches by design.
- [ ] **Courier text** is unaffected by kerning (monospace fonts have no pairs).
- [ ] Unkerned pairs (`Py`, `km`, `md`, `te` and others not in the AFM kerning table) look the same as before; they are *not* a regression but inherent to the font's published metrics.

### Milestone 0.0.3 — styled runs (bold, italic, monospace) + WinAnsi typographic punctuation

Sample: `/tmp/styled-full.pdf` from the styled_pdf demo at the bottom of this file.

- [ ] All four fonts visibly distinct:
  - [ ] **Helvetica** for body text (sans-serif, regular weight).
  - [ ] **Helvetica-Bold** is thicker/heavier than the regular face.
  - [ ] *Helvetica-Oblique* is slanted (italic look).
  - [ ] `Courier` is monospace (every glyph the same width, slab-serif feel).
- [ ] Font switches happen mid-line cleanly — no gap, no overlap between styled fragments.
- [ ] No font is rendered as a fallback (no warning glyphs, no Times New Roman where you expected Helvetica).
- [ ] **Em dash** (—) renders as a visible long horizontal line, not blank, not a short hyphen.
- [ ] **Curly quotes** (' and ") render as curly punctuation, not as straight ASCII quotes or blanks.
- [ ] **Ellipsis** (…) renders as three closely-spaced dots, not blank, not three separate periods.
- [ ] Text remains crisp and selectable; copy/paste from the viewer recovers the original characters (modulo the U+2014/0x97 ToUnicode caveat — see *Known limitations* below).
- [ ] All pages have consistent margins (1 inch).

### Pending milestones — append checklists here when the milestone lands

- [ ] **0.0.4 (markdown parser)**: when the input is `**bold**`, the output renders as bold. When `*italic*`, it renders italic. When `` `code` ``, it renders monospace. No stray asterisks or backticks visible. Headings render with appropriate size hierarchy (eventually). Etc.

## Known limitations (NOT bugs)

- Text extracted by `pdftotext` from base-font PDFs *without* an explicit `ToUnicode` CMap can lose typographic punctuation in the extraction (em dash becomes blank in extracted text). This is a `pdftotext` limitation, not a rendering bug. The PDF *renders* correctly. **Adding ToUnicode CMaps is a v0.2 task** — for v0.1 we accept that copy/paste of em dashes may not survive perfectly in all readers.
- Codepoints outside WinAnsi (CJK, full emoji, most non-Latin scripts) render as `?`. Documented as a v0.1 limitation in README; lifts in v0.2/0.3 with TTF embedding.

## How to regenerate

Sample-generation scripts live in `examples/` (planned). For now, the inline scripts in each milestone's commit message produce the sample PDFs. Until the `examples/` dir lands, regenerate manually:

```bash
cd ~/inkmd
.venv/bin/python <<'EOF'
# Milestone 0.0.1
from inkmd.pdf import hello_world_pdf
open('/tmp/hello.pdf','wb').write(hello_world_pdf())

# Milestone 0.0.2
from inkmd.pdf import text_pdf
text = "\n\n".join(f"Paragraph {i}: the quick brown fox jumps over the lazy dog." for i in range(60))
open('/tmp/multi.pdf','wb').write(text_pdf(text))

# Milestone 0.0.3
from inkmd.layout import Run
from inkmd.pdf import styled_pdf
paragraphs = [
    [
        Run("Welcome to ", "Helvetica", 12),
        Run("inkmd", "Helvetica-Bold", 12),
        Run(" — the only pure-Python markdown to PDF compiler that runs anywhere Python runs.", "Helvetica", 12),
    ],
    [
        Run("This paragraph mixes ", "Helvetica", 12),
        Run("bold emphasis", "Helvetica-Bold", 12),
        Run(", ", "Helvetica", 12),
        Run("italic phrases", "Helvetica-Oblique", 12),
        Run(", and ", "Helvetica", 12),
        Run("inline code", "Courier", 12),
        Run(" — note the em dashes, curly “quotes,” and ellipses… now render visibly.", "Helvetica", 12),
    ],
]
open('/tmp/styled-full.pdf','wb').write(styled_pdf(paragraphs))
EOF
```

Then open each `/tmp/*.pdf` and walk the relevant checklist above.
