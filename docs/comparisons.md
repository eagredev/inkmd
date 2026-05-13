# Why inkmd, and not the alternatives

There are several existing ways to turn markdown into PDF. Each has a real audience, and inkmd does not displace any of them — it occupies a niche that the others don't fit. This is the honest version of "why would I pick this one".

If your existing pipeline works, **keep it**. inkmd is for the specific case where the alternatives' tradeoffs hurt.

## Quick chooser

| Your situation | Pick |
|---|---|
| You already have Pandoc + LaTeX installed and aren't shipping anywhere | Pandoc + LaTeX |
| You're rendering HTML to PDF and markdown is just one input format | WeasyPrint (or Puppeteer if you can afford the install) |
| You need CSS theming, custom page chrome, fine typographical control | WeasyPrint |
| You need full Unicode (CJK, emoji, RTL) right now | WeasyPrint or markdown-it-py + WeasyPrint |
| You're rendering markdown to PDF from inside a Python process, in an Alpine container, on Lambda, on Windows-without-admin, on a locked-down CI runner | **inkmd** |
| You need byte-identical reproducible output for signed docs / audit trails | **inkmd** |
| You're building an LLM agent that produces PDFs and don't want to subprocess Chrome | **inkmd** |

## The tools

### WeasyPrint

[WeasyPrint](https://weasyprint.org/) takes HTML+CSS and produces a PDF. You add a markdown stage in front of it (typically `markdown-it-py` or `python-markdown`) and you have a markdown→PDF pipeline.

**Strengths:** Real CSS engine. Real typographic features. Page boxes, columns, paged-media specifics. Mature and well-maintained. Probably the right answer for most users.

**Why inkmd exists despite WeasyPrint:**
- WeasyPrint depends on Pango, Cairo, GObject — system libraries that often total 350–550MB and have to be installed via `apt-get` / `brew` / `pacman`. This breaks Alpine containers (the default for AWS Lambda / Fly / minimal CI runners), breaks Windows machines without admin rights, and inflates Docker images significantly.
- WeasyPrint cold-starts in roughly 500–800ms even for a one-page document. inkmd cold-starts in ~110ms.
- WeasyPrint isn't deterministic out of the box — it embeds dates, has fontconfig-dependent rendering. Useful PDFs, but not bit-for-bit reproducible across machines.

If your environment is "any Linux box with package-install access" or "macOS dev laptop", WeasyPrint is probably better. If your environment is "an Alpine container running on AWS Lambda" or "a Steam Deck", inkmd is probably better.

### markdown-it-py and friends, then WeasyPrint

The "modular" pipeline: a separate markdown parser converts to HTML, then WeasyPrint converts HTML to PDF.

**Strengths:** Best CommonMark conformance available in Python (markdown-it-py is ~100% on the spec test suite). Plug-in ecosystem. Clean separation of concerns.

**Why inkmd exists:**
- Same WeasyPrint dependency story applies.
- You pay for two parsers (markdown→HTML→PDF) where you only need one (markdown→PDF). For high-throughput cases this matters.
- The intermediate HTML is the wrong tool's representation for PDF output. Some constructs (page-aware layouts, exact byte determinism) are harder to control through an HTML stage.

inkmd's bet is that the markdown→HTML→PDF stack is a historical accident. Markdown is a structured-text format; PDF is a structured-text format; HTML is a different model with its own concerns (responsive layout, JavaScript, accessibility tagging) that the PDF stage has to undo.

### Pandoc + LaTeX (via `pdflatex` / `xelatex`)

[Pandoc](https://pandoc.org/) is the most complete document-conversion tool in existence. Through LaTeX it produces beautiful PDFs.

**Strengths:** Best-in-class typography. Full math support. Extensive markdown flavour handling. The right tool for academic papers, books, and professionally typeset content.

**Why inkmd exists:**
- The LaTeX install (texlive) is several GB on Linux, often unbundled by distro into many subpackages with confusing failure modes.
- Pandoc itself isn't small either.
- LaTeX errors are notoriously unfriendly. A markdown table that doesn't fit cleanly produces a multi-page LaTeX trace, not a helpful "your table is too wide" message.
- Pandoc is GPL — a non-issue for most users, but blocks some closed-source / commercial use.

If you're producing a book, a thesis, or a paper, use Pandoc + LaTeX. If you're producing a project README or a CV or a release-note PDF, inkmd is enough.

### Headless Chrome / Puppeteer / Playwright

Spin up a headless browser, give it HTML rendered from your markdown, ask it to "Print to PDF".

**Strengths:** Pixel-perfect HTML+CSS+JavaScript rendering. If you can render it in a browser, you can produce it as a PDF.

**Why inkmd exists:**
- Chromium install: 250–400MB of system binaries. Slow to install in CI, unable to install in tightly constrained environments.
- Cold start: 5 to 15 seconds typically, even for a one-page document. The browser is doing far more work than you need.
- Each PDF run uses real memory (200–400MB peak), so concurrency is expensive.
- Production headless-Chrome setups historically have a complex security and stability story.

If you're already running a Chrome instance for other reasons (web scraping, screenshot service), reuse it. Otherwise the install cost is hard to justify for a tool that should be one Python wheel.

### wkhtmltopdf

[wkhtmltopdf](https://wkhtmltopdf.org/) uses an older WebKit to render HTML to PDF.

**Why inkmd exists despite wkhtmltopdf:**
- wkhtmltopdf is [deprecated as of 2023](https://github.com/wkhtmltopdf/wkhtmltopdf/issues/5104). The maintainer announced end-of-life. No further fixes.
- Multiple unpatched CVEs from the deprecated Qt + WebKit dependency tree.
- Doesn't render modern HTML/CSS properly even before deprecation.

Useful for historical setups; not a serious option for new code in 2026.

### PyMuPDF / pymupdf-based tools

[PyMuPDF](https://pymupdf.readthedocs.io/) wraps MuPDF, a C PDF library. Various wrappers add markdown→PDF on top.

**Strengths:** Fast. Mature C PDF engine. Excellent existing-PDF manipulation (split, merge, extract).

**Why inkmd exists:**
- PyMuPDF is a compiled C extension. Doesn't build cleanly on Alpine musl without specific wheels. Carries its own ABI compatibility story.
- Most wrappers (markdown-pdf, etc.) implement a partial subset of markdown — they're typically not CommonMark-conformant.
- The package is AGPL-licensed (commercial licensing available). Same concern as borb.

PyMuPDF is the right tool for processing existing PDFs. Less of a fit when generating from scratch.

### borb

[borb](https://github.com/jorisschellekens/borb) is a pure-Python PDF library that includes a markdown reader.

**Why inkmd exists despite borb:**
- borb is **AGPL-licensed**. Using it in any closed-source product or commercial service that doesn't open-source itself requires a paid commercial licence.
- inkmd is **MIT-licensed**: use it in anything, no commitments, no paperwork.

If your project is itself AGPL or you don't mind buying a commercial licence, borb is a serious option. inkmd's MIT licence is the differentiator for most users who can't or don't want to pay or open-source.

### fpdf2 + markdown helper

[fpdf2](https://py-pdf.github.io/fpdf2/) is a pure-Python PDF library. It has a tiny `write_html` helper that accepts a markdown-ish subset.

**Why inkmd exists:**
- fpdf2's markdown reader handles only a small subset (basic bold/italic, simple tables). Not CommonMark-conformant.
- inkmd parses the full spec-defined surface; fpdf2's helper is essentially for sprinkling formatted text into manually-constructed PDF pages.

If you're already using fpdf2 for low-level PDF construction and just need a sentence of formatted text, fpdf2's helper is fine. inkmd is for "I have a markdown document and want a PDF of it".

### `Python-Markdown`, `mistune`, `markdown2` (parsers, no PDF stage)

These are markdown parsers without a PDF backend. You'd pair them with WeasyPrint or similar.

**Why inkmd exists:**
- Two of them (`Python-Markdown`, `markdown2`) [explicitly reject CommonMark as a goal](https://github.com/Python-Markdown/markdown/issues/851). Their output diverges from what GitHub renders.
- `mistune` is fast but [explicitly not CommonMark-conformant](https://mistune.lepture.com/) ("insane tests" ignored).
- inkmd targets CommonMark 0.31.2 measured against the spec test suite, so "what GitHub showed you" is what you get.

If you're already using one of these parsers for markdown→HTML elsewhere in your stack and don't need PDF, keep using them. If you're starting fresh and you want PDF, inkmd is direct.

## Where inkmd is honestly worse

Being clear about the tradeoffs:

- **No CSS theming.** inkmd's typography is fixed (Helvetica or Times, two page sizes, set spacing rules). If you need custom fonts, colours, layouts, you're better off with WeasyPrint.
- **No headers, footers, page numbers** in v0.2. Tracked for v0.3.
- **No full Unicode.** v0.2 supports WinAnsi (Western European). CJK, Cyrillic, emoji render as `?` until v0.3 adds font embedding. WeasyPrint handles Unicode out of the box.
- **No page-splitting for oversized tables.** A table taller than one page overflows. v0.3.
- **No accessibility / tagged PDF.** v1.0+.
- **No CommonMark `block-level HTML`.** Raw `<table>...</table>` at top level renders as text. v0.3.

If any of these matter, use a different tool — that's what they're for.

## The honest summary

inkmd is the answer to a specific question: **how do I turn markdown into a PDF, from inside a Python process, in an environment that won't let me install Chrome or a system-libraries-heavy alternative?**

For that question, the alternatives don't fit. For most other questions, they do.

The four claims inkmd makes:

1. **Zero system dependencies.** One pure-Python wheel.
2. **Byte-deterministic output.** Hash-stable PDFs across runs.
3. **Measured CommonMark conformance.** 85.0% on the public spec suite at v0.2, with the gaps documented in [`docs/conformance.md`](conformance.md).
4. **MIT-licensed.** Use it anywhere.

If those four matter for what you're building, inkmd fits. If they don't, the alternatives are usually a better choice. There's no shame in either direction.
