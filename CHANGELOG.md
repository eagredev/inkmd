# Changelog

All notable changes to `inkmd` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet. Next milestone is v0.2.0 — see the [roadmap](README.md#roadmap).

## [0.1.0] — 2026-05-12

Initial public release. Pure-Python markdown-to-PDF compiler with zero system dependencies, MIT-licensed, byte-deterministic output.

### Added

#### CommonMark support

- Paragraphs with line wrapping
- ATX (`#`…`######`) and Setext headings
- Ordered and unordered lists, with arbitrary nesting and tight/loose detection
- Blockquotes — nested, multi-paragraph, can wrap any block type
- Fenced code blocks with preserved whitespace, language tag (info string), and soft-wrap on long lines
- Indented code blocks
- Code spans
- Full left/right-flanking emphasis algorithm, including rule of 3, intraword-underscore rule, and triple-`***` rendering as nested italic-bold
- Backslash escapes
- Thematic breaks (`---`, `***`, `___`)
- Inline links `[text](url)` with optional titles
- Angle-bracket autolinks `<url>`

#### GFM extensions

- Pipe tables with left / center / right column alignments and content-aware widths
- Bare-URL autolinks: `https://…`, `http://…`, `www.…`, `host.tld/path`
- Email autolinks (auto-prefixed with `mailto:`)
- Strikethrough (`~~text~~`)

#### Visual output

- Clickable PDF `/Link` annotations on every URL (inline and autolinks)
- Blue underlined link text
- Light-grey background tint behind fenced code blocks
- Thin grey vertical rules for blockquotes; stacked side-by-side for nested quotes
- Tinted table headers with full grid borders
- AFM-correct kerning emitted via TJ arrays for Helvetica and Times
- Strikethrough drawn as a thin horizontal bar at glyph mid-height
- WinAnsi character encoding: em-dash, en-dash, curly quotes, ellipsis, most Western European glyphs

#### API and CLI

- Library API: `inkmd.compile(md_text, *, page_size, family, autolinks) -> bytes` and `inkmd.render_file(in_path, out_path, ...)`
- CLI: `inkmd in.md -o out.pdf`, with stdin/stdout support, `--page-size`, `--family`, `--no-autolinks`, `--version`
- Two font families: Helvetica (default, sans-serif) and Times (serif); code always uses Courier
- Two page sizes: Letter (default) and A4

#### Determinism

- Byte-identical PDF output for the same markdown input on every platform, every Python version, every run
- No real-time clocks, no random IDs, no platform-dependent iteration order

#### Examples and docs

- [`examples/hero-sample.md`](examples/hero-sample.md) — half-page quarterly-report sample used as the README hero image
- [`examples/inkmd-brief.md`](examples/inkmd-brief.md) — two-page project brief written in inkmd-renderable markdown; the artefact for "look what inkmd output actually looks like"
- [`examples/torture-test.md`](examples/torture-test.md) — comprehensive feature exercise covering every supported construct
- [`LIZARD-AUDIT.md`](LIZARD-AUDIT.md) — pre-release cyclomatic-complexity audit and v0.2 refactor candidates

### Known limitations

These are documented v0.1 constraints, not bugs — see the [roadmap](README.md#roadmap) for when they lift:

- **Codepoints outside WinAnsi** (CJK, Cyrillic, emoji, most non-Latin scripts, plus odds like the rightwards arrow `U+2192`) render as `?`. v0.2 lifts this with TTF font embedding.
- **Images** are not yet embedded. v0.2.
- **Task lists** (`- [ ]` / `- [x]`) are not yet recognised. v0.2.
- **Tables don't split across pages** — a table taller than one page will overflow. v0.2.
- **Tables inside blockquotes** are silently dropped (table detection runs at document level only). v0.2.
- **Headers, footers, and page numbers** are not yet supported. v0.2.

### Tests

497 tests across 23 files, all passing. End-to-end PDF validity verified via `qpdf --check`.

[Unreleased]: https://github.com/eagredev/inkmd/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/eagredev/inkmd/releases/tag/v0.1.0
