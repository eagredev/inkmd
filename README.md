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

**Pre-v0.1.** Not yet usable. Skeleton stage. See the [roadmap](#roadmap) below for what's coming.

## Install (when released)

```sh
pip install inkmd
```

Or, for the single-file zipapp deployment:

```sh
curl -O https://github.com/eagredev/inkmd/releases/latest/download/inkmd.pyz
python inkmd.pyz in.md -o out.pdf
```

## Usage (planned API)

CLI:

```sh
inkmd in.md -o out.pdf
inkmd in.md > out.pdf
inkmd < in.md > out.pdf
inkmd in.md --page-size letter --no-deterministic -o out.pdf
```

Library:

```python
import inkmd

# Compile markdown text to PDF bytes
pdf_bytes = inkmd.compile(md_text)

# Or convert files directly
inkmd.render_file("input.md", "output.pdf")
```

## What `inkmd` supports (v0.1 target)

- CommonMark baseline (paragraphs, headings, lists, blockquotes, code blocks, code spans, emphasis, links)
- GFM extensions: pipe tables, fenced code with language tag, strikethrough, task lists
- Page sizes: A4 (default), Letter
- 14 standard PDF fonts (Helvetica / Times / Courier variants, Symbol, ZapfDingbats)
- WinAnsi character encoding
- Deterministic output: same input → byte-identical PDF, every time, on every platform

## What `inkmd` doesn't support (yet)

- **Images** — planned for v0.2.
- **Custom fonts / TTF / OTF embedding** — planned for v0.2. Means **v0.1 is Latin-1 / WinAnsi only**: no CJK, no Cyrillic, no emoji, no most non-Latin scripts. It also means the actual visible rendering depends on which Helvetica clone the reader's system provides (see below).
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

`inkmd` is deterministic by default. The same markdown input produces byte-identical PDF output on every platform, every Python version, every run. This is supported via:

- A fixed `CreationDate` (no real-time clock)
- `SOURCE_DATE_EPOCH` environment variable support
- No random IDs in object generation
- Stable iteration order throughout

Useful for: version-controlled documents, signed/hashed PDFs, reproducible CI builds, audit trails.

Disable with `--no-deterministic` (uses current time) if you need timestamps.

## Roadmap

- **v0.1** — Core: markdown → PDF for the subset above, library + CLI, MIT, deterministic.
- **v0.2** — **Font embedding** (Nimbus Sans bundled by default; user-supplied TTF/OTF supported). Solves both the cross-platform-rendering question and Unicode coverage in one milestone. Also: image embedding (PNG, JPEG), headers/footers, page numbers.
- **v0.3** — Tagged PDF / accessibility, TOC generation, hyperlinks.
- **post-v1.0** — Optimisations, additional output sizes, PDF/A consideration.

## Licence

MIT. See [LICENSE](LICENSE).

## Acknowledgements

The 14 standard PDF fonts and their AFM metric files are public-domain artefacts published by Adobe ([adobe-type-tools/Core14_AFMs](https://github.com/adobe-type-tools/Core14_AFMs)). PDF format reference: ISO 32000-1.
