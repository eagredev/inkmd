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
- **Custom fonts / TTF / OTF embedding** — planned for v0.2 or v0.3. Means **v0.1 is Latin-1 / WinAnsi only**: no CJK, no Cyrillic, no emoji, no most non-Latin scripts.
- **Tagged PDF / PDF/UA accessibility** — under consideration for v0.3+.
- **PDF/A archival format** — not planned.
- **Math (LaTeX-style)** — out of scope. Use Pandoc + LaTeX if you need math.
- **HTML passthrough** — out of scope by design. `inkmd` is markdown → PDF directly.
- **Page numbers / headers / footers** — planned for v0.2.
- **Themes / CSS** — out of scope. Markdown's value is honest constraints; don't bring CSS back in.

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
- **v0.2** — Images (PNG, JPEG), headers/footers, page numbers, TTF embedding for Unicode.
- **v0.3** — Tagged PDF / accessibility, TOC generation, hyperlinks.
- **post-v1.0** — Optimisations, additional output sizes, PDF/A consideration.

## Licence

MIT. See [LICENSE](LICENSE).

## Acknowledgements

The 14 standard PDF fonts and their AFM metric files are public-domain artefacts published by Adobe ([adobe-type-tools/Core14_AFMs](https://github.com/adobe-type-tools/Core14_AFMs)). PDF format reference: ISO 32000-1.
