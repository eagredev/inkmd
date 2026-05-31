# How inkmd works

A technical walk-through of what's inside `inkmd` for readers who want to know how a markdown-to-PDF compiler with color emoji stays around 9,600 lines of logic, has zero runtime dependencies, and still produces output that holds up against tools 100x its size.

## The premise: direct compilation

Most markdown-to-PDF tools work in two passes. They parse markdown to HTML, then hand the HTML to a browser engine (Chrome, WebKit, Pango) to lay out and rasterise into PDF. This is the path of least resistance, since you reuse a battle-tested HTML renderer, and it carries the cost. Your tool now depends on the renderer's install footprint, its bugs, and its release cadence.

`inkmd` skips the middle step. Markdown goes through a parser, an AST, a layout pass, and straight to PDF byte emission. There is no intermediate HTML, no browser, no CSS. The whole pipeline is around 9,600 lines of pure-Python logic (about a third of that is the CommonMark parser; the color-emoji OpenType reader is around 900 of them). Adding a feature usually means adding one block of code that takes the AST node and emits PDF, not coordinating with a separate rendering engine that doesn't know it should care.

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

The whole determinism property cost about zero lines of code; it cost some discipline at API design time. The PDF info dictionary doesn't include a `/CreationDate` entry at all, because writing it deterministically would require a fixed value (boring) and writing it from the wall clock would break the property. An opt-in timestamp flag (`SOURCE_DATE_EPOCH`-driven, for users who want a real creation date) is a candidate for a later release; for now inkmd simply doesn't write one, and the output is hash-stable as a result.

The payoff is real. Hash the markdown, hash the PDF, store both. Two months later, regenerate the PDF from the same markdown and the hash is unchanged. CI runs that emit PDF artefacts can verify the artefact hasn't drifted. Signed audit documents have a stable artefact-level identity that survives every Python patch release.

## The single-byte font encoding, and what it still can't do

The honest limitation inkmd carries is the single-byte text-font encoding. PDF's 14 base fonts are spec-mandated and free, but they're single-byte fonts. Codepoints outside WinAnsi (CJK, Cyrillic, Greek, most non-Latin scripts) have no byte to spell them with and fall back to `?`. Adding a per-font `/Differences` array can buy a few glyphs from Symbol or ZapfDingbats but mixes typefaces visibly, and the proper fix for *text* is TTF outline embedding, which is queued for a later release. That work would parse TTF files, extract outlines and metrics, embed them as CID-keyed fonts, and route encoding through the embedded font's character map. The parser, render, and layout layers wouldn't need to change; it lands in `fonts.py` and `pdf.py`.

Emoji are the one part of "outside WinAnsi" that inkmd v0.2 *does* render, and the reason it could is worth its own section, because the intuition most people have about it is backwards.

## Color emoji as bitmap glyphs

The naive assumption is that color emoji are the hard case and monochrome would be easier. For inkmd the opposite is true, and it falls out of how modern emoji fonts are built.

Google's Noto Color Emoji stores each glyph not as a vector outline but as an embedded PNG, in a pair of OpenType tables called `CBLC` (the location/index) and `CBDT` (the data). A crisp-at-any-size *vector* color format also exists (COLRv1: layered paths with gradients and compositing), and supporting that would mean writing an outline parser plus a gradient-and-transform rendering engine with thirty-odd paint-node types. The bitmap path needs none of that. inkmd **already** embeds PNGs as PDF Image XObjects (that is how the image-embedding feature works). So drawing a real emoji is: find the glyph, pull its PNG bytes out of `CBDT` verbatim, and hand them to the image path that already exists. Color is the *easy* route here; vector would have been the fifty-times-harder one.

The work splits into a reader and a renderer.

**The reader** (`emoji_font.py`) is a small hand-rolled OpenType parser, no `fonttools` or any third-party dependency, in keeping with the rest of the project. It reads the table directory, then three things on demand:

- `cmap` **format 12** maps a Unicode codepoint to a glyph id (format 12 is the 32-bit segmented map emoji fonts use), and **format 14** handles variation sequences, the `U+FE0F` "render this as emoji, not text" presentation selector.
- `CBLC`/`CBDT` walking turns a glyph id into the bytes of its embedded PNG, reading the strike's index subtables to locate the glyph and the bitmap metrics to place it.
- `GSUB` **type-4 ligature lookups** are what compose multi-codepoint emoji. This is the part that is easy to underestimate. A flag (regional-indicator pair), a skin-toned thumbs-up, a ZWJ family sequence: none of these are single `cmap` entries. They are *ligatures*, sequences of base glyphs that a GSUB lookup substitutes with one combined glyph. Skip GSUB and you get the component glyphs side by side instead of the real emoji. One non-obvious detail surfaced during the build and is worth recording: Noto keys these ligatures on the sequence with `U+FE0F` *stripped out*, so the lookup has to drop presentation selectors before matching.

**The renderer** sits in `emoji.py` and the existing layers. A splitter walks inline text and gathers emoji clusters (a base codepoint plus any glue: ZWJ, skin-tone modifiers, the keycap combiner `U+20E3`, regional-indicator pairs), resolves each cluster to a glyph through the longest matching ligature, and emits the result as a run carrying an `EmojiImage` instead of text. From there the emoji is just an image: `layout` reserves a text-sized box for it and positions it on the baseline; `pdf` draws it as an Image XObject before the text pass and skips it in the text loop. Identical XObjects are de-duplicated by a stable id so a document full of the same checkmark embeds the PNG once.

Two design choices keep this from leaking into the rest of the system. A document with no emoji never loads the 10MB font: a cheap codepoint pre-scan gates an `lru_cache`d loader, so the cost is paid only when an emoji actually appears. And the "what if the font isn't there" policy (the single-file zipapp ships without the font, and `INKMD_NO_EMOJI=1` disables it) is carried on a `contextvars.ContextVar` scoped per compile rather than threaded as a parameter through every recursive inline-render call, which keeps the signatures clean and is thread- and async-safe. In that font-less mode an emoji becomes either a readable `[rocket]`-style label or nothing, never a `?`.

The bitmap tradeoff is honest and documented: PNGs are resolution-fixed, so an emoji scaled up to a very large heading softens slightly. At inline text size it is invisible. If crispness at large sizes ever becomes a real complaint, COLRv0 (flat vector layers, no gradient engine) is the natural upgrade.

## The other v0.2 additions

Image embedding (PNG including indexed-palette with `tRNS` transparency, plus JPEG), reference links and images, the inline-HTML allow-list, hard line breaks, indented code blocks inside list items, task lists, and the URL-scheme filter are each focused additions without architectural impact. The pipeline shape stays the same: a new AST node, a render branch, maybe a layout primitive, and a PDF emission rule. Tall tables now split across pages, repeating the header (the renderer emits per-row groups in row-local coordinates and the layout places them top-to-bottom, breaking at row boundaries); horizontal fitting for very wide tables and headers/footers/page numbers are still ahead, on the v0.3 roadmap.

## Reading the code

Start with `src/inkmd/__init__.py`. It defines the entire public API (`compile` and `render_file`) and points at the four modules. Read them in dependency order: `parser` first (the most lines but the most self-contained), then `render`, then `layout`, then `pdf`. The frozen-dataclass AST in `ast.py` is what everything passes around. Read it before the parser if you want a map of what the parser produces. The color-emoji code lives off to the side in `emoji.py` (the splitter and fallback policy) and `emoji_font.py` (the OpenType reader); `render` and `layout` call into them but the four-layer spine is unchanged.

Tests are organised one file per feature. If you're trying to understand how strikethrough is handled across the four layers, `tests/test_strikethrough.py` exercises all of them. The torture-test markdown at `examples/torture-test.md` is the closest thing to a single-page reference of everything inkmd can render; the rendered PDF (`inkmd examples/torture-test.md -o torture.pdf`) is the visual proof.

The complexity profile is documented in [`LIZARD-AUDIT.md`](../LIZARD-AUDIT.md): twelve functions exceed the standard CCN-15 warn threshold, none exceed CCN 35, and the audit explains why each one was left as-is and which two are the standing refactor candidates (`paginate_runs` and `_render_table`).
