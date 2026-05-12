# inkmd

**Pure-Python markdown → PDF compiler. Zero system dependencies. MIT-licensed. Deterministic by default.**

`inkmd` compiles markdown into PDF without wrapping a browser, LaTeX, or HTML/CSS engine. It's a direct compiler: markdown in, PDF bytes out, no apt-get required.

## Why?

Every other markdown → PDF tool needs heavy system dependencies:

- **wkhtmltopdf** is deprecated since 2023, with unpatched CVEs.
- **Chrome headless / Puppeteer** is 200MB+ and adds 5-15s of cold-start latency.
- **WeasyPrint** needs Pango, cairo, and GObject — 350-550MB of system packages, and breaks on Alpine Linux and Windows.
- **Pandoc + LaTeX** is a 3GB texlive install.
- **PyMuPDF-based tools** don't build on Alpine musl.
- **`borb`** is the closest pure-Python alternative, but it's AGPL — unusable in closed-source or commercial projects without a paid licence.

`inkmd` is designed for the places where those tools fail: Alpine Docker images, AWS Lambda functions, locked-down CI runners, Windows hosts, Steam Decks. If Python runs, `inkmd` runs.

## Status

**v0.1 — feature-complete.** Library + CLI both work. 478 tests across 22 files. Stdlib-only Python 3.9+.

## Install

```sh
pip install inkmd
```

Or, for the single-file zipapp deployment:

```sh
curl -O https://github.com/eagredev/inkmd/releases/latest/download/inkmd.pyz
python inkmd.pyz in.md -o out.pdf
```

## Usage

CLI:

```sh
inkmd in.md -o out.pdf              # file in, file out
inkmd in.md > out.pdf               # file in, stdout out
inkmd < in.md > out.pdf             # stdin in, stdout out
inkmd in.md -o out.pdf --page-size A4 --family times
inkmd in.md -o out.pdf --no-autolinks
```

Library:

```python
import inkmd

# Compile markdown text to PDF bytes
pdf_bytes = inkmd.compile(md_text)

# Or convert files directly
inkmd.render_file("input.md", "output.pdf")

# Options
pdf_bytes = inkmd.compile(
    md_text,
    page_size="A4",          # or "letter" (default)
    family="times",          # or "helvetica" (default)
    autolinks=False,         # opt out of GFM bare-URL/email detection
)
```

## What `inkmd` supports

- **CommonMark**: paragraphs, ATX (1-6) + Setext headings, ordered + unordered lists with nesting and tight/loose detection, blockquotes (nested, multi-paragraph, can wrap any block type), fenced code blocks with preserved whitespace and soft-wrap, code spans, emphasis (full left/right-flanking algorithm including rule of 3 and intraword-underscore), thematic breaks, inline links `[text](url)`, autolinks `<url>`.
- **GFM extensions**: pipe tables with alignments, fenced code with language tag, bare-URL and email autolinks (toggle with `--no-autolinks` / `autolinks=False`).
- **Page sizes**: A4, Letter.
- **Fonts**: Helvetica family (sans, default) or Times family (serif). Code uses Courier. All 14 standard PDF fonts are available internally.
- **Visual style**: clickable PDF `/Link` annotations on URLs, blue underlined link text, light-grey background fill behind fenced code, thin grey rules for blockquotes (stacked side-by-side for nested), tinted table headers with full grid borders, AFM-correct kerning emitted via TJ arrays.
- **WinAnsi character encoding** (em-dash, en-dash, curly quotes, ellipsis, most Western European glyphs).
- **Deterministic output**: same input → byte-identical PDF, every time, on every platform.

## What `inkmd` doesn't support (yet)

- **Images** — planned for v0.2.
- **Custom fonts / TTF / OTF embedding** — planned for v0.2. Means **v0.1 is WinAnsi only**: codepoints outside Latin-1 / WinAnsi (CJK, Cyrillic, emoji, most non-Latin scripts) render as `?`. v0.2 lifts this by embedding font outlines into the PDF.
- **Strikethrough and task lists** — GFM extensions deferred to v0.2 alongside the inline-extensions pass.
- **Tables that split across pages** — tables place atomically. A table taller than one page will overflow. v0.2.
- **Tables inside blockquotes** — table detection runs at document level only. Tables nested inside a blockquote are silently dropped. v0.2.
- **Tagged PDF / PDF/UA accessibility** — under consideration for v0.3+.
- **PDF/A archival format** — not planned.
- **Math (LaTeX-style)** — out of scope. Use Pandoc + LaTeX if you need math.
- **HTML passthrough** — out of scope by design. `inkmd` is markdown → PDF directly.
- **Page numbers / headers / footers** — planned for v0.2.
- **Themes / CSS** — out of scope. Markdown's value is honest constraints; don't bring CSS back in.

## A note on font rendering in v0.1

`inkmd` v0.1 uses PDF's **14 base fonts** (Helvetica, Times, Courier, Symbol, ZapfDingbats and their variants). These are spec-mandated to be available in every conforming PDF reader, so we don't ship any font files — the output stays tiny and dependency-free.

The trade-off is that the *actual rendering* depends on which Helvetica (or Times, etc.) the reader's system provides:

- **macOS** ships Helvetica Neue (real Helvetica). Renders as designed.
- **Windows** with Adobe Reader ships real Helvetica. Renders as designed.
- **Linux** typically substitutes Nimbus Sans (URW++'s free Helvetica clone). Renders very similarly but with slightly different side bearings — spacing between glyphs can look subtly different.
- **Mobile** (iOS/Android) ships system Helvetica/Roboto variants. Mostly fine.

The advance widths are correct everywhere (PDF readers honor the AFM-published metrics), so layout — page breaks, line wrapping, paragraph flow — is identical across systems. What varies is the precise glyph shape *within* each advance-width box, which can produce slightly different visual spacing.

For most use cases this is fine. If you need pixel-identical rendering across every system (e.g. for signed/archival documents), wait for **v0.2 font embedding**, which will bundle font outlines inside each PDF.

## Determinism

`inkmd` produces byte-identical PDF output for the same markdown input on every platform, every Python version, every run. No real-time clocks, no random IDs, no platform-dependent iteration order. Useful for version-controlled documents, signed/hashed PDFs, reproducible CI builds, and audit trails.

## Roadmap

- **v0.1** — Core: markdown → PDF for the subset above, library + CLI, MIT, deterministic. **Shipped.**
- **v0.2** — Font embedding (full Unicode), images, strikethrough, task lists, headers/footers, page numbers, page-splitting for oversized tables.
- **v0.3** — Tagged PDF / accessibility, TOC generation, cross-references.
- **post-v1.0** — Optimisations, additional page sizes, PDF/A consideration.

## Licence

MIT. See [LICENSE](LICENSE).

## Acknowledgements

The 14 standard PDF fonts and their AFM metric files are public-domain artefacts published by Adobe ([adobe-type-tools/Core14_AFMs](https://github.com/adobe-type-tools/Core14_AFMs)). PDF format reference: ISO 32000-1.
