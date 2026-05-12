# How inkmd works

A technical walk-through of what's inside `inkmd` for readers who want to know how a markdown-to-PDF compiler stays under 4,000 lines, has zero runtime dependencies, and still produces output that holds up against tools 100x its size.

## The premise: direct compilation

Most markdown-to-PDF tools work in two passes. They parse markdown to HTML, then hand the HTML to a browser engine (Chrome, WebKit, Pango) to lay out and rasterise into PDF. This is the path of least resistance, since you reuse a battle-tested HTML renderer, and it carries the cost. Your tool now depends on the renderer's install footprint, its bugs, and its release cadence.

`inkmd` skips the middle step. Markdown goes through a parser, an AST, a layout pass, and straight to PDF byte emission. There is no intermediate HTML, no browser, no CSS. The whole pipeline is around 3,500 lines of pure-Python logic. Adding a feature usually means adding one block of code that takes the AST node and emits PDF, not coordinating with a separate rendering engine that doesn't know it should care.

This shape is what makes the zero-dependency promise possible. PDF's specification is finite. Markdown's syntax is finite. Layout rules for body text are finite. Once you stop trying to inherit from HTML's behaviour, the problem fits in your head.

## Four layers

The pipeline has four modules, each strictly above the previous one. No layer imports anything from a higher layer; the only data flowing upward is types.

1. **`parser`** turns markdown text into a tuple of frozen-dataclass AST nodes. Knows about CommonMark and GFM. Knows nothing about fonts, page sizes, or PDF.
2. **`render`** lowers AST nodes into `RenderedBlock` records: per-block runs, spacing hints, indent, link/colour/strike decorations. Carries font state through inline nesting. Knows about fonts (for measurement) but emits no bytes.
3. **`layout`** wraps the runs into pages. Positions each `PositionedRun` against a page coordinate system, emits background rectangles for code-block tints, vertical rules for blockquotes, underlines and link annotations, and bars for strikethrough. Knows about page geometry.
4. **`pdf`** serialises pages into PDF bytes. Knows the PDF spec: object dictionaries, content streams, the cross-reference table, link annotations. Knows nothing about markdown.

You can swap any layer without disturbing the others. Want a different output format? Replace `pdf`. Want a different page geometry? Replace `layout`. The parser doesn't change.

The dependency direction matters because it bounds your test surface. Parser tests don't care about fonts. Layout tests don't care about PDF byte format. PDF emission tests don't care about markdown. Each layer's tests pin its contract with the layer above and below; you don't end up with brittle end-to-end-only tests that break when anything moves.

## The emphasis algorithm

The single most non-trivial piece of CommonMark is `process_emphasis` (§6.2). Naive implementations of `*text*` work for the easy cases and produce wrong nesting for everything interesting: `***bold-italic***`, `**foo**bar**baz**`, `*foo**bar**`, `_intra_word_`. Getting it right takes a real algorithm.

`inkmd` implements the spec's algorithm faithfully. The inline tokeniser walks the text once, emitting one of: a `Text` token, a `Code` token (opaque), a `Delim` token (a run of `*`, `_`, or `~` with pre-computed left/right-flanking properties), a `Link` token (pre-parsed `[text](url)` node), or an `AutoLink` token. The flanking rules (§6.2) are computed at tokenise time from the immediate neighbour characters.

Then `_resolve_emphasis` walks the delimiter runs, pairing openers with closers under the spec's "rule of 3": an opener and closer can pair only if `opener.length + closer.length` is *not* a multiple of 3, or each length *is* individually a multiple of 3. When a pair matches, the algorithm eats 2 characters from each side (for `Strong`) or 1 (for `Emphasis`), creates the span node, and (this is the part naive implementations get wrong) *preserves the remainder delimiters with their flanking metadata*. The walk then resumes from the opener's position so a remaining 1-char opener can pair with a remaining 1-char closer.

That last bit is how `***bold-italic***` produces the correct `Emphasis(Strong(...))` nesting. The first pass eats 2 of the 3 leading and trailing asterisks, emitting `Strong`. The remaining 1-char delimiters are still active and still left/right-flanking, so the next pass pairs them as `Emphasis` around the just-emitted `Strong`. The user gets `<em><strong>bold-italic</strong></em>` without the parser having to special-case triple-asterisk anywhere.

GFM strikethrough plugs into the same machinery. `~` is added as a third delimiter character; the tokeniser only emits a strike-delim for exactly length-2 runs (per GFM); `_resolve_emphasis` always eats 2 characters for `~` and emits `Strikethrough` instead of `Strong`/`Emphasis`. The reuse is the point: adding a new "two-sided wrapper" inline construct takes one branch in the resolution loop and no parallel pass.

## AFM metrics and kerning

A markdown-to-PDF compiler that doesn't kern text looks like browser-rendered HTML printed to PDF: technically correct, visibly amateur. PDF's 14 base fonts come with public-domain Adobe Font Metrics (AFM) files that publish per-glyph widths and per-pair kerning offsets, about 4,000 kerning pairs for Helvetica alone. `inkmd` ships these tables, generated and frozen at build time, in `_kerning_data.py` (about 4,700 lines).

The width tables are indexed by WinAnsi byte. WinAnsi is the single-byte encoding PDF uses for the base fonts: ASCII in the lower half, Latin-1 supplement plus Microsoft's typographic-punctuation block (em dash, curly quotes, ellipsis, and so on) in the upper half. The tokeniser maps Unicode codepoints to WinAnsi bytes before measurement, so an em-dash from your markdown comes out the byte-position the font expects, and the width lookup hits the right entry.

At emission time, runs of text are encoded into PDF's `TJ` operator, a text-showing operator that interleaves string fragments and integer offsets. Between every adjacent pair of glyphs, the kerning offset from the AFM is emitted as the offset value. The output looks like `[(To) -100 (gether)] TJ` for "Together" with a kerning adjustment between `T` and `o`. Adobe Reader, Apple Preview, evince, and Chrome all honour this. The kerning carries across every conforming reader.

This is also why output stays deterministic across platforms. The widths and kerning offsets are *advance widths* baked into the PDF, not glyph positions chosen by the reader's renderer. Whichever Helvetica clone (Nimbus Sans on Linux, real Helvetica on macOS) the reader uses, the layout (line breaks, paragraph flow, page splits) is identical. Only the glyph shapes inside each pre-allocated advance-width box can vary, and only slightly.

## Determinism, for free

`inkmd`'s byte-for-byte determinism wasn't an after-the-fact retrofit; it's a consequence of not doing things that introduce non-determinism. There's no `datetime.now()` in the PDF generation path. There are no random object IDs: every PDF object number is assigned sequentially as objects are created. There's no `dict` iteration that depends on insertion order influenced by parsing speed. There's no `set` ordering in hot paths.

The whole determinism property cost about zero lines of code; it cost some discipline at API design time. The PDF info dictionary doesn't include a `/CreationDate` entry at all in v0.1, because writing it deterministically would require a fixed value (boring) and writing it from the wall clock would break the property. v0.2 will add an opt-in `--no-deterministic` flag with `SOURCE_DATE_EPOCH` support so users who want a real timestamp can opt in; v0.1 just doesn't write one.

The payoff is real. Hash the markdown, hash the PDF, store both. Two months later, regenerate the PDF from the same markdown and the hash is unchanged. CI runs that emit PDF artefacts can verify the artefact hasn't drifted. Signed audit documents have a stable artefact-level identity that survives every Python patch release.

## What v0.2 changes

The honest limitation of v0.1 is the single-byte font encoding. PDF's 14 base fonts are spec-mandated and free, but they're single-byte fonts. Codepoints outside WinAnsi (CJK, Cyrillic, emoji, even the Unicode rightwards arrow at `U+2192`) have no byte to spell them with and fall back to `?`. Adding a per-font `/Differences` array can buy a few glyphs from Symbol or ZapfDingbats but mixes typefaces visibly, and the proper fix is TTF font embedding.

v0.2's font-embedding work parses TTF font files at compile time, extracts the outlines and metrics inkmd needs, embeds them in the PDF as CID-keyed fonts, and routes character encoding through the embedded font's character map. Roughly 1,500 to 2,500 lines of new code, all in `fonts.py` and `pdf.py`; the parser, render, and layout layers don't need to change. The same milestone unlocks user-supplied custom fonts as a side effect: bring your own TTF, inkmd embeds it.

The other v0.2 items (image embedding, page-splitting for oversized tables, headers/footers/page numbers, task lists) are each a focused addition without architectural impact. The pipeline shape stays the same.

## Reading the code

Start with `src/inkmd/__init__.py`. It's 60 lines, defines the entire public API, and points at the four modules. Read them in dependency order: `parser` first (the most lines but the most self-contained), then `render`, then `layout`, then `pdf`. The frozen-dataclass AST in `ast.py` is what everything passes around. Read it before the parser if you want a map of what the parser produces.

Tests are organised one file per feature. If you're trying to understand how strikethrough is handled across the four layers, `tests/test_strikethrough.py` exercises all of them. The torture-test markdown at `examples/torture-test.md` is the closest thing to a single-page reference of everything inkmd can render; the rendered PDF (`inkmd examples/torture-test.md -o torture.pdf`) is the visual proof.

The complexity profile is documented in [`LIZARD-AUDIT.md`](../LIZARD-AUDIT.md): twelve functions exceed the standard CCN-15 warn threshold, none exceed CCN 35, and the audit explains why each one was left as-is for v0.1 and which two are queued for v0.2 refactoring.
