# Changelog

All notable changes to `inkmd` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet. v0.3 will target visually-identical rendering for the spec-test edges where the current AST shape differs but the rendered PDF is correct (blockquote-inside-list, mixed-indent siblings). See the [roadmap](README.md#roadmap).

## [0.2.0] - 2026-05-13

Conformance, breadth, and the v0.2 design principle.

inkmd v0.2 covers the **sane-use-case bar**: most real-world markdown renders correctly, with the remaining failing spec tests confined to niche edges (raw block-level HTML, pathological nesting). Conformance against the public spec suites:

- **CommonMark 0.31.2**: 554/652 = **85.0%** (up from 60.4%, +160 tests)
- **GFM extensions**: 20/28 = **71.4%** (up from 60.7%, +3 tests)

The full per-section breakdown plus a real-world impact audit of remaining failures is in [`docs/conformance.md`](docs/conformance.md).

### Added

#### CommonMark features

- **Reference links and reference images** (`[label]: url "title"` definitions; `[text][label]`, `[label][]`, and `[label]` reference forms; image variants with `!` prefix). Unicode case-fold + whitespace-collapsed label normalisation. Definitions resolve from anywhere in the document.
- **Hard line breaks** (CommonMark section 6.7): two-or-more trailing spaces and backslash-before-newline both emit hard breaks.
- **Indented code blocks** at the document level AND inside list items (section 4.4 + 5.2). The common README pattern of placing a code sample under a bullet now renders correctly.
- **Image-inside-link** (`[![badge](badge.png)](/repo)`): the GitHub-README clickable-badge pattern parses correctly.
- **Tab-aware indent accounting**: tabs are preserved verbatim inside code blocks (per section 2.2) and counted as column-stops for indent decisions, rather than being expanded to spaces at parse time.
- **Blockquote lazy continuation** (section 5.1): an unprefixed paragraph line continues a quoted paragraph rather than terminating the quote.
- **HTML passthrough (Option B curated safe subset)**: a parser-level inline HTML tokeniser plus a render-time allow-list. Typed tags (`<sub>`, `<sup>`, `<u>`, `<mark>`, `<kbd>`, `<s>`/`<strike>`/`<del>`, `<br>`) get PDF semantics; passthrough tags (`<span>`, `<em>`, `<strong>`, etc.) unwrap to their content; script/style/iframe are dropped with content. Off by default for renderer use, on by default for parsing. See [`docs/design/html-passthrough.md`](docs/design/html-passthrough.md).
- **Multi-backtick code spans** (per section 6.1): an N-backtick run closes only on the next run of exactly N backticks, so `` `` `code` `` `` works.
- **HTML5 entity references** in inline text (`&auml;`, `&copy;`, `&#x2014;`, etc.) decode via the stdlib `html.entities.html5` table.

#### GFM extensions

- **Task list items** (`- [ ]` / `- [x]`): the prefix is recognised, stripped from the rendered content, and the PDF renders a coloured checkbox marker in place of the bullet.

#### Images

- **PNG and JPEG embedding** via PDF XObjects (`/DCTDecode` for JPEG, `/FlateDecode` with `/Predictor 15` for PNG). PNG colour types 0 (grayscale) and 2 (RGB) are supported in v0.2; RGBA and indexed PNG are queued for v0.3.
- **Block-level image rendering** for image-only paragraphs (single image on a line renders with its natural aspect ratio, capped at page width).
- **Inline image rendering** with alt-text fallback when the source is missing or unreadable.
- **Local file paths** and **`data:` URIs** are loaded by default. **HTTP(S) URLs** require explicit opt-in via `--allow-remote-images` (CLI) or `allow_remote_images=True` (library), preserving inkmd's zero-network default.

#### Security

- **URL scheme allow-list (on by default)**: links to `http`, `https`, `mailto`, `tel`, `ftp`, and `xmpp` schemes pass through as clickable; anything else (`javascript:`, `data:`, `vbscript:`, `file:`, custom schemes) renders as plain text with no annotation. Disable via `--allow-unsafe-urls` (CLI) or `safe=False` (library). The threat model in [`docs/security.md`](docs/security.md) covers the full posture.
- **HTML allow-list** drops `<script>`, `<style>`, `<iframe>`, `<object>`, and similar tag bodies entirely; the filter is render-time and the dropped content does not reach the PDF.

#### Performance

- **Deeply nested blockquotes** (10,000+ levels) are now handled iteratively in the URL filter, HTML filter, and image loader to avoid Python recursion limits. The renderer's O(N²) blockquote-rule placement is documented in `docs/security.md` and triggers only on pathological synthetic inputs.

#### CLI

- New flags: `--allow-unsafe-urls`, `--allow-remote-images`, `--no-html`.
- `inkmd --show-config` is not added (no config file in v0.2); the CLI surface stays minimal.

### Changed

- **AST**: `Document` gained `link_references` (a tuple of `(label, url, title)` triples plus a `link_reference_table()` helper). New inline nodes: `Image`, `HtmlInline`, `Subscript`, `Superscript`, `Underline`, `Mark`, `Kbd`, `HardBreak`. `ListItem` gained a `task: bool | None` field for GFM task lists.
- **Conformance numbers** in [`docs/conformance.md`](docs/conformance.md) refreshed to reflect the v0.2 measurement (`554/652` CommonMark, `20/28` GFM extensions).

### Fixed

- **Bare-URL autolinks** with unbalanced parens (`www.example.com/path)+suffix`) now consume the trailing `)+suffix` per GFM section 6.9, trimming only at the end of the URL.
- **Link URL parsing** for empty URLs (`[link]()`), paren-form titles (`[link](url (title))`), multi-line URL/title across one newline, URL-entity decoding (`[a](b&auml;c)` → `b%C3%A4c`), and backslash-escape ASCII-punct rule (so `foo\bar` in a URL preserves the literal `\`).
- **Email autolinks** (`<addr@host>`) now reject backslash and other non-RFC characters in the local-part.
- **URL percent-encoding** at HTML serialise time encodes `[` and `]` as `%5B` / `%5D` to match the CommonMark reference renderer.
- **Code spans** preserve a meaningful single trailing space at end-of-paragraph; soft-break whitespace stripping happens at serialise time per spec.
- **Ordered list markers** other than `1.` no longer interrupt an open paragraph (`14. cont.` mid-sentence stays paragraph).
- **Thematic break vs list marker** ordering: `* * *` at the outer list's marker column is a thematic break, not a sibling list item.

### Known limitations (carried to v0.3)

- **Raw HTML blocks** (`<table>...</table>` as a top-level construct) render as inline text rather than passing through verbatim. CommonMark HTML-blocks section is 2/44 = 4.5%.
- **Blockquote inside a list item**: a `> note` line inside a list item still renders as paragraph text rather than opening a blockquote.
- **Deep mixed-indent list siblings** where every line has off-by-one indent (CommonMark example 310): inkmd produces a structurally nested but visually similar result.
- **Tab-as-list-content-indent**: a leading tab as the indent past a list item content column is recognised; deeper combinations (tabs after blockquote markers, double-tabs as list content) are queued.

### Tests

649 unit tests + 652 CommonMark spec tests + 28 GFM extension spec tests, all measurable and passing within the documented gap. End-to-end PDF validity verified via `qpdf --check`.

## [0.1.0] - 2026-05-12

Initial public release. Pure-Python markdown-to-PDF compiler with zero system dependencies, MIT-licensed, byte-deterministic output.

### Added

#### CommonMark support

- Paragraphs with line wrapping
- ATX (`#` through `######`) and Setext headings
- Ordered and unordered lists, with arbitrary nesting and tight/loose detection
- Blockquotes (nested, multi-paragraph, can wrap any block type)
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
- Bare-URL autolinks: `https://...`, `http://...`, `www....`, `host.tld/path`
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

- [`examples/hero-sample.md`](examples/hero-sample.md): half-page quarterly-report sample used as the README hero image
- [`examples/inkmd-brief.md`](examples/inkmd-brief.md): two-page project brief written in inkmd-renderable markdown
- [`examples/torture-test.md`](examples/torture-test.md): comprehensive feature exercise covering every supported construct
- [`LIZARD-AUDIT.md`](LIZARD-AUDIT.md): pre-release cyclomatic-complexity audit and v0.2 refactor candidates

### Known limitations

These are documented v0.1 constraints, not bugs. See the [roadmap](README.md#roadmap) for when they lift:

- **Codepoints outside WinAnsi** (CJK, Cyrillic, emoji, most non-Latin scripts, plus odds like the rightwards arrow `U+2192`) render as `?`. v0.2 lifts this with TTF font embedding.
- **Images** are not yet embedded. v0.2.
- **Task lists** (`- [ ]` / `- [x]`) are not yet recognised. v0.2.
- **Tables don't split across pages**: a table taller than one page will overflow. v0.2.
- **Tables inside blockquotes** are silently dropped (table detection runs at document level only). v0.2.
- **Headers, footers, and page numbers** are not yet supported. v0.2.

### Tests

501 tests across 24 files, all passing. End-to-end PDF validity verified via `qpdf --check`.

[Unreleased]: https://github.com/eagredev/inkmd/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/eagredev/inkmd/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/eagredev/inkmd/releases/tag/v0.1.0
