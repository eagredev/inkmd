# Visual checklist

Automated tests verify *bytes on the page*, not *what humans see*. They are necessary but insufficient for a rendering tool. Every milestone produces a sample PDF; this file lists what to look for when opening it in a real viewer.

**Tip for visual review on Linux**: render samples in **Times** family rather than Helvetica. The Linux fallback (Nimbus Roman) is metrically much closer to real Adobe Times than Nimbus Sans is to Adobe Helvetica, so review on a Steam Deck / Linux laptop will look closer to what Mac/Windows users will see:

```python
inkmd.compile(md_text, family="times")
```

The library default stays Helvetica.

The discipline:

1. After each milestone, run the sample-generation script (see "How to regenerate").
2. Open the resulting PDF in a viewer (Okular, Evince, macOS Preview, Adobe Reader, Chrome — ideally at least two of these).
3. Walk the relevant checklist below. Each item is a yes/no question.
4. If any item is "no" → file the bug, don't ship.
5. If the checklist itself is missing a category for a regression that occurred → add the category before continuing.

## Why this exists

Background: in milestone 0.0.3, the em dash rendered as a blank glyph because the font dictionary didn't declare `/Encoding /WinAnsiEncoding`. `qpdf --check` passed. `pdftotext` extracted the bytes correctly. The fault only surfaced when a human opened the PDF and noticed the missing dash. **The lesson:** byte-level tools agree with each other about what's on the page, not with humans about what's visible.

A `pdftoppm`-based rasterising test could automate some of this in future, but the cost of building it well is high and the cost of an opened-the-PDF-and-looked check is ~30 seconds per milestone. We keep this manual until the project ships v0.1.

## Validator coverage notes

Not every tool catches every kind of bug.

- **`file <pdf>`**: checks header and trailer markers. Tells you it's a valid PDF *file*. Catches structural-framing damage. Won't notice anything wrong with content streams or rendering.
- **`qpdf --check <pdf>`**: validates the object graph, xref offsets, stream encodings, encryption integrity. Does *not* validate content-stream operator arity. (Demonstrated during 0.0.3.1: a `Tm` operator with 2 args instead of 6 passed `qpdf --check` cleanly but rendered as a blank page.)
- **`pdftotext <pdf> -`**: parses the content stream more deeply and emits warnings like `Syntax Error (409): Too few (2) args to 'Tm' operator`. Catches operator-arity bugs `qpdf` misses. Strongly preferred for catching emission mistakes — run it on every sample PDF.
- **Viewer rendering**: catches encoding-vs-encoding mismatches, font-metric vs renderer-glyph mismatches, and any visual oddity that the parsers tolerate. Irreplaceable.

Rule of thumb: run `pdftotext <pdf> -` on every sample. If it reports any `Syntax Error`, the PDF is malformed even if `qpdf --check` is happy.

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

#### Milestone 0.0.4 — markdown parser (paragraphs only)

Sample: `/tmp/md-first.pdf` from `inkmd.compile(md_text)` where `md_text` contains 3-4 paragraphs separated by blank lines.

- [ ] Each `\n\n`-separated source paragraph appears as its own paragraph in the output.
- [ ] Internal newlines within a source paragraph flatten to single spaces (soft breaks).
- [ ] Multiple blank lines between paragraphs render the same as one (no extra spacing).
- [ ] Markdown literals that 0.0.4 doesn't yet interpret (`**bold**`, `*italic*`, `` `code` ``, `# heading`, `- list`) appear in the output **as literal characters**. This is expected for 0.0.4 — formatting recognition arrives in 0.0.5.
- [ ] Em dashes, curly quotes, ellipses still render correctly (regression from 0.0.3.1).
- [ ] `inkmd.compile(md_text)` and `inkmd.render_file(in_path, out_path)` both work without raising.

### Milestone 0.0.5 — inline formatting (bold / italic / code)

Sample: `/tmp/md-formatted-times.pdf` (or `-helvetica.pdf`) from `inkmd.compile()` with input containing `**bold**`, `*italic*`, `` `code` `` spans.

- [ ] `**bold**` text renders in **bold weight** with no asterisks visible.
- [ ] `*italic*` text renders in *italic* with no asterisks visible.
- [ ] `` `code` `` text renders in monospace (Courier) with no backticks visible.
- [ ] Mixed formatting on one line (plain, then bold, then italic, then code) shows clean font transitions with no overlap.
- [ ] Backticked content blocks internal formatting: `` `**not bold**` `` renders the asterisks literally in monospace, *as designed*.
- [ ] Unmatched delimiters (`**` with no closer) appear as literal text — parser is forgiving, not strict.

### Milestone 0.0.6 — CommonMark inline completeness

Sample: `/tmp/md-commonmark-times.pdf` from a markdown source mixing nested emphasis, underscore delimiters, intraword underscores, and backslash escapes.

- [ ] **Nested emphasis** works: `**bold containing *italic* inside**` renders the inner span in *bold-italic*, with no stray asterisks visible.
- [ ] **Underscore delimiters** work: `_italic_` and `__bold__` produce italic and bold respectively, indistinguishable in output from their asterisk counterparts.
- [ ] **Intraword underscore** is preserved: `snake_case_name` and `my_python_var` appear as literal text with underscores visible.
- [ ] **Intraword asterisks** DO emphasise: `intra*word*emph` produces `intra<i>word</i>emph` (per CommonMark spec — different from underscores).
- [ ] **Backslash escapes** work: `\*literal\*`, `\_literal\_`, `` \` `` all preserve their punctuation. `\\` produces a literal backslash.
- [ ] **Code spans remain opaque**: `` `**not bold**` `` shows literal asterisks in Courier; `` `\*also literal\*` `` keeps the backslashes too.
- [ ] **Mixed delimiters**: `__strong *emph* end__` and `*emph __strong__ end*` both nest correctly.

## Pending milestones — append checklists here when the milestone lands

- [ ] **0.0.7 (block constructs)**: `# Heading` renders larger and bold; `- item` renders as a bulleted list; `> quote` renders as a blockquote with indent.

## Known limitations (NOT bugs)

- **Font substitution.** v0.1 references PDF's 14 base fonts by name (Helvetica, Times, Courier, …) and does not embed font files. Readers without genuine Adobe Helvetica installed (most Linux systems, including Steam Deck) substitute a clone — typically **Nimbus Sans** on Ghostscript-based readers. Advance widths match, so layout positions are correct, but **glyph side-bearings differ slightly**, which makes spacing between visible ink look subtly different from Adobe Helvetica's published metrics. The same PDF on macOS Preview or Adobe Reader (which ship real Helvetica) will render closer to inkmd's intended spacing. This lifts in v0.2 with font embedding. **Verifying inkmd output on a Linux Steam Deck is testing rendering through Nimbus Sans, not through Helvetica.**
- Text extracted by `pdftotext` from base-font PDFs *without* an explicit `ToUnicode` CMap can lose typographic punctuation in the extraction (em dash becomes blank in extracted text). This is a `pdftotext` limitation, not a rendering bug. The PDF *renders* correctly. **Adding ToUnicode CMaps is a v0.2 task** — for v0.1 we accept that copy/paste of em dashes may not survive perfectly in all readers.
- Codepoints outside WinAnsi (CJK, full emoji, most non-Latin scripts) render as `?`. Documented as a v0.1 limitation in README; lifts in v0.2 with TTF embedding.

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
