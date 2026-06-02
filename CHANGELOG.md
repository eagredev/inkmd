# Changelog

All notable changes to `inkmd` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet. v0.3 will target visually-identical rendering for the spec-test edges where the current AST shape differs but the rendered PDF is correct (blockquote-inside-list, mixed-indent siblings), plus block-level raw HTML passthrough, headers/footers/page numbers, horizontal fitting for very wide tables (tall tables already split across pages in v0.2), text-font embedding for non-Latin scripts (CJK, Cyrillic), full RGBA PNG, and GIF. See the [roadmap](README.md#roadmap).

## [0.2.1] - 2026-06-02

A correctness release: re-verified every published benchmark and size claim, fixed a zipapp build bug, and hardened the test suite. No changes to the rendering or public API.

### Corrected (honesty)

The benchmark numbers published with 0.2.0 were measured on 2026-05-14, *before* color emoji was bundled into the package. Bundling the ~10 MB Noto Color Emoji font changed the install footprint, so the install-size claims were stale. They have been re-measured on 2026-06-02 and corrected:

- **Install size: was stated as 10.5 MB / "7.1x smaller" than WeasyPrint; actually 22.2 MB / 3.4x smaller.** The speed and memory advantages are unchanged (the font is disk weight, not runtime cost — it's only read when an emoji is present): ~6–7x faster cold-start, ~6x lower peak RSS.
- **Zipapp: was stated as ~300 KB; actually ~170 KB** after the build fix below.
- Test count updated to the real **808 tests across 34 files** (was variously stated as 649 or 788).
- CommonMark (85.0%) and GFM-extension (71.4%) conformance re-confirmed — unchanged.

### Fixed

- **Zipapp build swept in `__pycache__` / `.pyc` files**, making `inkmd.pyz` both bloated (up to ~1.3 MB depending on the build interpreter) and **non-deterministic** — two builds could differ byte-for-byte, contradicting the determinism guarantee. The build now excludes compiled bytecode; the zipapp is a deterministic ~170 KB on every supported Python.

### Added

- **Adversarial security test suite** (`tests/test_security_adversarial.py`, 19 tests) asserting on final compiled PDF bytes: `javascript:`/`data:`/`file:`/`vbscript:` links emit no `/URI` annotation; the emitter can never produce `/JavaScript`, `/Launch`, `/OpenAction`, `/EmbeddedFile`, or other dangerous PDF action types; `<script>`/`<style>`/`<iframe>` bodies are dropped; zero-network behaviour proven by monkeypatching the socket layer.
- Cross-Python verification: the full suite now passes on CPython 3.9 through 3.13 (two test-portability bugs fixed; the library itself was always correct across the range).

## [0.2.0] - 2026-05-31

Conformance, breadth, the v0.2 design principle, and color emoji.

inkmd v0.2 covers the **sane-use-case bar**: most real-world markdown renders correctly, with the remaining failing spec tests confined to niche edges (raw block-level HTML, pathological nesting). Conformance against the public spec suites:

- **CommonMark 0.31.2**: 554/652 = **85.0%** (up from 60.4%, +160 tests)
- **GFM extensions**: 20/28 = **71.4%** (up from 60.7%, +3 tests)

The headline visible-output change is **color emoji**: the emoji-as-`?` artefact that made output look broken to anyone who pasted a README into inkmd is gone. Emoji now render as color glyphs from a bundled font, including flags, skin tones, and ZWJ sequences. The full per-section conformance breakdown plus a real-world impact audit of remaining failures is in [`docs/conformance.md`](docs/conformance.md).

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
- **Tables split across pages.** A table taller than one page now breaks at a row boundary and continues on the next page with the header row repeated and each page-slice fully boxed, instead of overflowing off the bottom and silently losing rows. The renderer emits the table as per-row groups (row-local coordinates) and the layout places them top-to-bottom, paginating at row boundaries. Single-page tables are visually unchanged. (Very wide tables — too many columns to fit even at minimum width — still overflow the right edge; horizontal fitting is v0.3.)

#### Color emoji

- **Color emoji render as inline images** from a bundled copy of Google's Noto Color Emoji (SIL OFL 1.1, shipped unmodified). The previous behaviour rendered every emoji as `?`; that artefact is gone. Emoji render inline, in headings (scaled to the heading size), and in table cells.
- **Hand-rolled OpenType reader** (`emoji_font.py`), no `fonttools` or any third-party dependency. It parses `cmap` formats 12 and 14, walks the `CBLC`/`CBDT` bitmap tables to extract each glyph's embedded PNG verbatim, and applies `GSUB` type-4 ligature lookups. The extracted PNG reuses the same Image XObject path the image-embedding feature already uses.
- **Emoji sequences** compose correctly via GSUB ligatures: presentation selectors (`U+FE0F`/`U+FE0E`), regional-indicator flag pairs, skin-tone modifiers, ZWJ sequences (families, the rainbow flag), and keycaps (`0` through `9`, `#`, `*` followed by `U+20E3`).
- **Fallback for the font-less build.** The pip install bundles the font and renders all emoji in colour. The single-file zipapp ships without the font (it is the small "lite" artefact); there, and when `INKMD_NO_EMOJI=1` is set, emoji take a configurable fallback: `emoji_fallback="name"` (default) substitutes a readable `[rocket]`-style label, `emoji_fallback="drop"` omits them. Either way the `?` is gone in both tiers. The implementation note is in [`docs/design/emoji-rendering-plan.md`](docs/design/emoji-rendering-plan.md) and [`docs/internals.md`](docs/internals.md).

#### Images

- **PNG and JPEG embedding** via PDF XObjects (`/DCTDecode` for JPEG, `/FlateDecode` with `/Predictor 15` for PNG). PNG colour types 0 (grayscale), 2 (RGB), and 3 (**indexed/palette**) are supported. Indexed PNGs with a `tRNS` chunk get per-palette alpha decoded into a `/SMask` soft mask, so palette transparency renders correctly. Full RGBA (colour type 6) is queued for v0.3.
- **Block-level image rendering** for image-only paragraphs (single image on a line renders with its natural aspect ratio, capped at page width).
- **Inline image rendering** with alt-text fallback when the source is missing or unreadable.
- **HTML `<img>` support**: the `<img>` tag is promoted to the same image pipeline as markdown `![alt](url)` (riding the identical `base_dir`/`allow_remote` security gating — not a new surface). The `width` attribute is honoured as a display-width hint (capped to the text column, aspect preserved), and a wrapping `align`/`<center>` or an `align` on the tag positions a block image left/centre/right. The `<p align="center"><img><br>caption</p>` figure idiom common in GitHub READMEs embeds the image and renders the caption beneath it — so inkmd now renders its own README in full, hero included.
- **Local file paths** and **`data:` URIs** are loaded by default. **HTTP(S) URLs** require explicit opt-in via `--allow-remote-images` (CLI) or `allow_remote_images=True` (library), preserving inkmd's zero-network default.

#### Security

- **URL scheme allow-list (on by default)**: links to `http`, `https`, `mailto`, `tel`, `ftp`, and `xmpp` schemes pass through as clickable; anything else (`javascript:`, `data:`, `vbscript:`, `file:`, custom schemes) renders as plain text with no annotation. Disable via `--allow-unsafe-urls` (CLI) or `safe=False` (library). The threat model in [`docs/security.md`](docs/security.md) covers the full posture.
- **HTML allow-list** drops `<script>`, `<style>`, `<iframe>`, `<object>`, and similar tag bodies entirely; the filter is render-time and the dropped content does not reach the PDF.
- **The bundled emoji font is a static read-only package asset**, parsed only for the bytes of each glyph's embedded PNG. No font program is ever embedded in the output PDF and no executable font logic runs; emoji reach the PDF as the same inert Image XObjects as any other image. inkmd loads no font from the user's system or from the document.

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

#### Rendering robustness (adversarial render audit)

A multi-pass adversarial render audit surfaced and fixed a batch of layout edge cases that produced overflowing, clipped, or misplaced output rather than incorrect-but-contained output. Highlights:

- **Long unbreakable tokens** (URLs, code spans, identifiers) in narrow table cells and in prose now break at separators and camelCase boundaries with a character-level fallback, instead of overflowing the cell or the page margin. Styling is preserved across the break.
- **Table column widths** honour each column's minimum content width: a table too wide for the page overflows to the right rather than crushing columns to unreadable slivers, and right/centre-aligned cells clamp to the left cell edge so content never starts left of its own column.
- **Deeply nested list/quote indentation** is clamped so content always keeps a usable minimum width rather than marching off the right margin.
- **Code-block backgrounds inside blockquotes** tint the correct region: the grey fill and the quote rule no longer fight over the same pixels.
- **Table-cell decorations** (links, strikethrough, code-span backgrounds) and A4 page-width accounting were corrected.

A second, focused audit run just before release swept the new emoji and indexed-PNG surface and fixed:

- **Malformed PNGs that crashed compilation.** An indexed PNG missing its `IDAT` image data or its `PLTE` palette passed the dimension check but raised an uncaught error at emission. Such images now fall back to their alt text like any other unloadable image, so a single bad embed can never abort the whole document.
- **Emoji inside code spans and code blocks** now render as color images (or their textual fallback in the font-less build) instead of leaking a literal `?` from the WinAnsi encoder — emoji are the documented exception to the WinAnsi rule and now hold everywhere, monospace included.
- **Orphaned zero-width joiners.** A ZWJ emoji cluster the bundled font can't fully ligature decomposes into its component emoji; the joiners between them are now dropped rather than surfacing as `?`.
- **Soft hyphens** (U+00AD) are treated as the invisible optional-break hints they are and dropped, instead of printing a visible hyphen and stealing its width.
- **Bold-italic in table headers** composes correctly (`***x***` in a header keeps its italic), matching body cells.

### Known limitations (carried to v0.3)

- **Raw HTML blocks** (`<table>...</table>` as a top-level construct) render as inline text rather than passing through verbatim. CommonMark HTML-blocks section is 2/44 = 4.5%.
- **Blockquote inside a list item**: a `> note` line inside a list item still renders as paragraph text rather than opening a blockquote.
- **Deep mixed-indent list siblings** where every line has off-by-one indent (CommonMark example 310): inkmd produces a structurally nested but visually similar result.
- **Tab-as-list-content-indent**: a leading tab as the indent past a list item content column is recognised; deeper combinations (tabs after blockquote markers, double-tabs as list content) are queued.

### Tests

788 unit tests across 33 files + 652 CommonMark spec tests + 28 GFM extension spec tests, all measurable and passing within the documented gap. The emoji feature is tested against a synthetic in-memory CBDT/GSUB font, so the suite has no system-font dependency. End-to-end PDF validity verified via `qpdf --check`.

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
