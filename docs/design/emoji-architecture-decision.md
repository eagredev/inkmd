# Design decision: color emoji in a zero-dependency PDF compiler

**Status:** accepted and shipped in v0.2.0 (2026-05-31).
**Scope:** why inkmd renders *color* emoji (not monochrome, not `?`), why
that didn't betray the zero-dependency promise, and the engineering reframe
that made the "hard" version the easy one. Companion to
`emoji-bundling-tradeoff.md` (which covers the size tradeoff) and
`emoji-rendering-plan.md` (the phase-by-phase implementation plan).

## The problem

Before v0.2, every emoji rendered as `?`. This was not an emoji-specific bug:
`fonts.to_winansi_byte` maps *any* codepoint outside WinAnsi (emoji, CJK,
Greek, ...) to `?`, because the PDF base-14 fonts physically contain zero
glyphs for them. To a standard desktop user pasting a README into inkmd, the
`?` read as **"this tool is broken,"** not as "a documented limitation." It
was the single biggest credibility wince in the output.

Fixing it ran straight into inkmd's founding promise: **zero dependencies,
runs anywhere, deterministic.** Drawing a real 🚀 means embedding glyph data, and a font is exactly the
kind of heavyweight asset the project exists to avoid. The apparent options were all bad: ship `?` (looks broken), do
monochrome only (still need a font, only half-solves it), or take a font
dependency (betrays the promise).

## Why the hard version was actually the easy one

This came down to one observation: **color emoji via bitmaps is the
*easy* path, not the hard one. The usual "color is hard, mono is easy"
intuition is backwards here.**

Google's Noto Color Emoji stores each glyph, in its `CBDT` table, as an
**embedded PNG**. And inkmd *already embeds PNG and JPEG as PDF Image
XObjects* (the `cm`/`Do` placement path in `pdf.py`, built for the v0.2 image
feature). So rendering a color emoji is:

> extract the glyph's PNG bytes verbatim, hand them to the Image XObject
> path that already exists, and place it inline scaled to the font size.

No rasterizer, no new rendering primitive. The "hard" alternative would have
been **COLRv1 vector** emoji (crisp at any size): that needs a `glyf`/`CFF`
outline parser plus a gradient/transform/compositing engine (30+ paint-node
types), roughly **50× the work** for a benefit (crispness at huge sizes) that
is invisible at inline text size. Monochrome would *also* have required
embedding a font and writing the bitmap/outline path, for a worse result.

So color-bitmap was the least code and the best-looking default, and it
reused machinery inkmd already had and tested.

The seam that made this work was narrow: "draw a colored glyph" and "embed
a PNG" turn out to be the same operation, and inkmd was already good at the
second.

## Decisions

### Fidelity: bitmap color now; vector later only if asked.
CBDT PNG to Image XObject. The documented tradeoff: bitmaps soften when scaled
to very large headings or print sizes; at inline text size this is invisible.
COLRv0 (flat vector layers, no gradient engine) is the natural future upgrade
*if* crispness-at-scale ever becomes a real complaint, but it's a YAGNI bet
until then.

### Coverage: the full, unmodified font.
Bundle Noto Color Emoji **whole and unmodified**, not a curated subset. A
subset would shrink the file but ring-fence capability behind an arbitrary
"common emoji" line and create permanent, *invisible* coverage gaps. The day
a user needs an emoji outside the subset, it silently fails. Shipping the full
font means "if it's an emoji, it renders," and, because the font is
unmodified, there is no subsetter/font-writer code to maintain and no OFL
Reserved-Font-Name rename obligation (that rule only bites on *modified*
redistributed font files). The size cost of this choice, and why it's
acceptable, is the subject of `emoji-bundling-tradeoff.md`.

### Fallback: a readable name by default, never `?`.
When emoji *can't* render (the font-less zipapp, `INKMD_NO_EMOJI=1`, or a
glyph the font lacks), `split_text_into_runs` applies a fallback policy:
`"name"` (default) substitutes a readable `[rocket]`/`[flag:JP]`-style label
(a curated short-name map, with a `unicodedata.name()` slug fallback for the
long tail); `"drop"` omits it (zero width). Either way **the `?` is gone in
both tiers**: full install renders a color glyph; lite renders a legible
name. Per the consistency principle (see `consistency-principle.md`), this
fallback covers *all* unrepresentable codepoints, not just emoji.

Implementation note worth keeping: the fallback mode is threaded via a
**`ContextVar`** (`_fallback_mode` in `emoji.py`), scoped per `compile()`
call, not passed as a parameter through every recursive `_render_inline`
call. This avoided a noisy signature change across the render tree and is
thread/async-safe.

### Implementation: a hand-rolled OpenType reader, no `fonttools`.
Consistent with the rest of inkmd (the PDF layer is hand-written too), the
font is parsed by `emoji_font.py`, a from-scratch OpenType reader with no
third-party dependency. It parses `cmap` formats 12 (32-bit, where emoji live)
and 14 (variation sequences, U+FE0F/FE0E presentation selectors), walks the
`CBLC`/`CBDT` bitmap tables to extract each glyph's PNG verbatim, and applies
`GSUB` type-4 ligature lookups. Keeping it dependency-free means even the
full-featured install stays true to "zero *required* dependencies."

**The non-obvious correctness risk: GSUB ligatures.** Composed emoji are not
single `cmap` entries: a ZWJ family (👨‍👩‍👧), a regional-indicator flag (🇯🇵),
and a skin-tone modifier (👍🏽) are all built by *ligature lookup*. Skip GSUB
and the component glyphs render side-by-side instead of the intended single
emoji. This was flagged up front as the single most likely correctness bug,
and tested early against ZWJ families, flags, and skin tones. (The second
red-team audit later found a related leak, orphaned ZWJ joiners surfacing as
`?` when a cluster *couldn't* fully ligature, which confirmed this was the
right thing to worry about.)

## What "zero dependencies" actually means

Shipping a 10 MB font asset made it necessary to restate what "zero
dependencies" actually buys, versus what it was conflated with as a slogan.
The engineering value is: **installs anywhere, no C-extension platform
matrix, no supply-chain surface, deterministic output.** Every one of those
properties survives a bundled pure-data asset. "Zero deps" was never meant
to be a constraint against ever shipping data.

So the precise framing is **"zero *required* runtime dependencies"**: no
third-party packages, no system libraries, no network, no C extensions. A
bundled font (or, later, an optional heavyweight feature) doesn't break that;
it's data, not a dependency. This decoupling is why the emoji decision did
not break the promise.

## Alternatives rejected

| Alternative | Rejected because |
|-------------|------------------|
| Keep rendering `?` | The standout "looks broken" failure for normal users. |
| Monochrome emoji | Still needs a bundled font + a bitmap/outline path; worse result for ~equal cost. |
| COLRv1 vector emoji | ~50× the implementation (outline parser + gradient/compositing engine) for crispness invisible at inline size. |
| Curated emoji subset | Smaller file, but invisible capability cliffs + subsetter code + OFL rename obligation. |
| `fonttools` dependency | Betrays "zero required dependencies"; the hand-rolled reader keeps the promise. |
| OpenMoji / Twemoji art | OpenMoji is CC BY-SA (copyleft-viral on artwork); Twemoji is CC-BY graphics, not an OT font. Noto under OFL is the clean bundle-in-MIT choice. |

## Licensing (settled)

Noto Color Emoji ships under **SIL OFL 1.1**, which permits bundling inside an
MIT-licensed wheel. Obligations satisfied: `OFL.txt` ships alongside the font
in the package. Because inkmd extracts PNG bytes at runtime and redistributes
the font **unmodified**, the OFL Reserved-Font-Name rule (which only restricts
*modified* redistributed font files) does not trigger, so no rename is needed.
Generated PDFs carry no attribution obligation and embed no font program: the
emoji reach the PDF as inert Image XObjects, identical in kind to any other
embedded image.

## Cross-references

- `docs/design/emoji-bundling-tradeoff.md`: the ~50× size tradeoff and the
  reversibility design.
- `docs/design/emoji-rendering-plan.md`: phase-by-phase implementation.
- `docs/design/consistency-principle.md`: why the fallback covers all
  unrepresentable codepoints.
- `docs/internals.md`: the "Color emoji as bitmap glyphs" write-up.
- `docs/security.md`: bundled-font posture (no font program in output).
