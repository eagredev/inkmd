# inkmd

**Markdown to PDF, pure Python, zero dependencies. MIT-licensed. Deterministic.**

```sh
pip install inkmd
inkmd in.md -o out.pdf
```

That's the whole install. No system packages. No fonts to install. No Chrome binary. No `apt-get`. Works the same on macOS, Linux, Windows, Alpine, AWS Lambda, a locked-down CI runner, or a Steam Deck.

<p align="center">
  <img src="docs/images/hero-sample.png" alt="A quarterly report rendered by inkmd, showing headings, a styled paragraph with strikethrough, a blockquote, a right-aligned table with tinted header, a bulleted list, and a fenced Python code block with a grey background." width="640">
  <br>
  <em><a href="examples/hero-sample.md">examples/hero-sample.md</a> rendered through inkmd. Headings, inline styles, strikethrough, blockquote, GFM table, list, fenced code, and autolinked URL + email — all in one page.</em>
</p>

## What you get

- **A single pure-Python wheel.** No native extensions, no system libraries. Installs in under a second.
- **Faithful CommonMark + the parts of GFM people actually use:** tables, autolinks, strikethrough, fenced code with language tags. The [supported features](#supported-markdown) section has the full matrix.
- **PDFs that look right.** Real kerning (AFM-driven, emitted via TJ arrays), clickable links, tinted code-block backgrounds, blockquote rules that stack for nested quotes, table alignment, headings that breathe.
- **Byte-identical output for the same input.** No clocks, no random IDs. Useful for version control, signed PDFs, audit trails, reproducible CI.
- **Two layers of API:** a CLI and a `compile()` / `render_file()` library function. The whole public surface is two functions.

## Why this exists

Markdown to PDF is a solved problem in theory and a minefield in practice. Every other tool brings heavy system dependencies that don't survive the trip into an Alpine container, a Lambda function, or a Windows machine without admin rights.

| Tool | What goes wrong |
|------|-----------------|
| **wkhtmltopdf** | Deprecated since 2023. Unpatched CVEs. |
| **Chrome headless / Puppeteer** | 200MB+ install. 5–15s cold-start latency. |
| **WeasyPrint** | Needs Pango, cairo, GObject (350–550MB of system packages). Breaks on Alpine and Windows. |
| **Pandoc + LaTeX** | 3GB texlive install. |
| **PyMuPDF-based tools** | Don't build on Alpine musl. |
| **`borb`** | AGPL — unusable in closed-source or commercial projects without a paid licence. |

`inkmd` runs anywhere Python runs. It's the markdown-to-PDF compiler you'd write yourself if you had a free weekend and didn't want to take a dependency on a browser.

## Use cases

- **CI documentation pipelines.** Compile READMEs, release notes, or changelogs to PDF as a build artefact, in a stripped-down container, without `apt-get`.
- **Agent-generated documents.** LLM agents that need to deliver a PDF (CVs, reports, summaries) can call `inkmd.compile()` directly — no subprocess, no shell-out, no Chrome.
- **Reproducible audit trails.** Hash the markdown, hash the PDF — same input gives the same output bytes. Useful for compliance, signed reports, version-controlled docs.
- **Serverless rendering.** Lambda + zero system dependencies = a PDF endpoint that cold-starts in well under a second.
- **Restricted environments.** Locked-down CI runners, embedded hardware, anywhere installing a 200MB browser isn't an option.

## Status

**v0.1 — feature-complete, MIT-licensed.** 497 tests across 23 files. Stdlib-only, Python 3.9+. Byte-deterministic output. Built in a single intense day; the [torture test](examples/torture-test.md) covers everything `inkmd` can render.

## Install

From PyPI:

```sh
pip install inkmd
```

Or grab the single-file zipapp — no `pip` install required:

```sh
curl -O https://github.com/eagredev/inkmd/releases/latest/download/inkmd.pyz
python inkmd.pyz in.md -o out.pdf
```

## Usage

### CLI

```sh
inkmd in.md -o out.pdf              # file in, file out
inkmd in.md > out.pdf               # file in, stdout out
inkmd < in.md > out.pdf             # stdin in, stdout out
inkmd in.md -o out.pdf --page-size A4 --family times
inkmd in.md -o out.pdf --no-autolinks
inkmd --version
```

### Library

```python
import inkmd

# Compile markdown text to PDF bytes
pdf_bytes = inkmd.compile(md_text)

# Or convert files directly
inkmd.render_file("in.md", "out.pdf")

# Options (same on both functions)
pdf_bytes = inkmd.compile(
    md_text,
    page_size="A4",          # or "letter" (default)
    family="times",          # or "helvetica" (default)
    autolinks=False,         # opt out of GFM bare-URL/email detection
)
```

The public API is intentionally narrow: two functions, no classes to instantiate, no state to manage. The CLI is a thin argparse wrapper around `compile()`.

## Supported markdown

### CommonMark

| Feature | inkmd |
|---------|:---:|
| Paragraphs with line wrapping | Yes |
| ATX headings (`#` … `######`) | Yes |
| Setext headings (`===` / `---`) | Yes |
| Ordered lists, arbitrary `start` | Yes |
| Unordered lists (`-` / `*` / `+`) | Yes |
| Nested lists, mixed marker types | Yes |
| Tight vs. loose list detection | Yes |
| Blockquotes | Yes |
| Nested and multi-paragraph blockquotes | Yes |
| Blockquotes wrapping any block type | Yes |
| Fenced code blocks | Yes |
| Code block language tag (info string) | Yes |
| Indented code blocks | Yes |
| Code spans (`` `code` ``) | Yes |
| Emphasis (`*`, `_`) | Yes |
| Strong emphasis (`**`, `__`) | Yes |
| Triple `***` becomes nested italic-bold | Yes |
| Rule of 3 + intraword-underscore | Yes |
| Backslash escapes | Yes |
| Thematic breaks | Yes |
| Inline links `[text](url)` | Yes |
| Inline link titles | Yes |
| Angle-bracket autolinks `<url>` | Yes |
| Images `![](...)` | v0.2 |
| Reference-style links | v0.2 |
| HTML blocks / inline HTML | not planned |

### GFM extensions

| Feature | inkmd |
|---------|:---:|
| Pipe tables | Yes |
| Table column alignments | Yes |
| Bare URL autolinks (`https://…`, `www.…`) | Yes |
| Bare host autolinks (`host.tld/path`) | Yes |
| Email autolinks | Yes |
| Strikethrough `~~text~~` | Yes |
| Task lists `- [ ]` / `- [x]` | v0.2 |

### Visual output

- Clickable PDF `/Link` annotations on every URL — inline links and autolinks alike.
- Blue underlined link text.
- Light-grey background tint behind fenced code blocks.
- Thin grey vertical rules for blockquotes; stack side-by-side for nested quotes.
- Tinted table headers with full grid borders and per-column alignment.
- AFM-correct kerning emitted via TJ arrays (Helvetica and Times both fully kerned).
- Strikethrough drawn as a thin horizontal bar at glyph mid-height.

### Typography

- Helvetica family (default) or Times family. Code uses Courier.
- Standard PDF letter and A4 page sizes.
- WinAnsi character encoding — em-dash, en-dash, curly quotes, ellipsis, most Western European glyphs.
- Codepoints outside WinAnsi (CJK, Cyrillic, emoji, most non-Latin scripts) render as `?` in v0.1. v0.2 lifts this with font embedding.

## Determinism

`inkmd` produces **byte-identical** PDF output for the same markdown input on every platform, every Python version, every run. No real-time clocks, no random IDs, no platform-dependent iteration order.

If you hash the markdown and the PDF, the relationship is stable forever. Useful for version-controlled documents, signed/hashed PDFs, reproducible CI builds, and audit trails.

## What `inkmd` doesn't do yet

| Feature | When | Why |
|---------|------|-----|
| Images | v0.2 | Needs decoding + embedding logic; out of scope for the minimum lovable v0.1 |
| TTF / OTF font embedding | v0.2 | v0.1 uses PDF's 14 base fonts — tiny output, no font files to ship, but limits codepoints to WinAnsi |
| Task lists | v0.2 | GFM extension; needs list-marker prefix scan |
| Headers, footers, page numbers | v0.2 | Needs a per-page chrome system |
| Page-splitting for oversized tables | v0.2 | Tables currently place atomically and overflow if taller than a page |
| Tables inside blockquotes | v0.2 | Table detection runs at document level only |
| Tagged PDF / PDF/UA accessibility | v0.3+ | Under consideration |
| PDF/A archival format | — | Not planned |
| Math (LaTeX-style) | — | Out of scope. Use Pandoc + LaTeX. |
| HTML passthrough | — | Out of scope by design. `inkmd` is markdown to PDF, not HTML to PDF. |
| Themes / CSS | — | Out of scope. Markdown's value is honest constraints — don't bring CSS back in. |

## How it works

Four layers, each strictly above the previous:

1. **`parser`** — single-pass container-aware block parser plus a CommonMark inline tokeniser. Produces a frozen-dataclass AST.
2. **`render`** — lowers AST blocks to `RenderedBlock` records with runs, spacing, indent, decorations. Carries font and link state through inline nesting.
3. **`layout`** — wraps runs into pages, positions each `PositionedRun` against the page coordinate system, emits background rectangles for code blocks, vertical rules for blockquotes, underline + annotation pairs for links, and bars for strikethrough.
4. **`pdf`** — serialises pages into PDF bytes. Text via `Tj`/`TJ`-with-kerning, graphics via `rg`/`re`/`f`, link annotations via per-page `/Annots` arrays.

No layer imports a higher one. The whole pipeline is ~3,500 lines of pure-Python logic plus ~4,700 lines of generated AFM kerning tables — that's it. The complexity profile is documented in [`LIZARD-AUDIT.md`](LIZARD-AUDIT.md).

<details>
<summary><strong>A note on font rendering in v0.1</strong> — click to expand</summary>

`inkmd` v0.1 uses PDF's **14 base fonts** (Helvetica, Times, Courier, Symbol, ZapfDingbats and their variants). These are spec-mandated to be available in every conforming PDF reader, so we don't ship any font files — the output stays tiny and dependency-free.

The trade-off is that the *actual rendering* depends on which Helvetica (or Times, etc.) the reader's system provides:

- **macOS** ships Helvetica Neue (real Helvetica). Renders as designed.
- **Windows** with Adobe Reader ships real Helvetica. Renders as designed.
- **Linux** typically substitutes Nimbus Sans (URW++'s free Helvetica clone). Renders very similarly but with slightly different side bearings — spacing between glyphs can look subtly different.
- **Mobile** (iOS/Android) ships system Helvetica/Roboto variants. Mostly fine.

The advance widths are correct everywhere (PDF readers honour the AFM-published metrics), so layout — page breaks, line wrapping, paragraph flow — is identical across systems. What varies is the precise glyph shape *within* each advance-width box, which can produce slightly different visual spacing.

For most use cases this is fine. If you need pixel-identical rendering across every system (e.g. for signed/archival documents), wait for **v0.2 font embedding**, which will bundle font outlines inside each PDF.

</details>

## Roadmap

- **v0.1** — Core: CommonMark + GFM subset, library + CLI, MIT, deterministic. **Shipped.**
- **v0.2** — Font embedding (full Unicode), images, task lists, headers/footers/page numbers, page-splitting for oversized tables, tables-in-blockquotes.
- **v0.3** — Tagged PDF / accessibility, TOC generation, cross-references.
- **post-v1.0** — Optimisations, additional page sizes, PDF/A consideration.

## Licence

MIT. See [LICENSE](LICENSE).

## Acknowledgements

The 14 standard PDF fonts and their AFM metric files are public-domain artefacts published by Adobe ([adobe-type-tools/Core14_AFMs](https://github.com/adobe-type-tools/Core14_AFMs)). PDF format reference: ISO 32000-1.

## About

Built by [Dylan Moir](https://www.linkedin.com/in/dylanmoir/). If `inkmd` saves you a fight with WeasyPrint or a 200MB Chrome install in your CI, a star on the repo is plenty.
