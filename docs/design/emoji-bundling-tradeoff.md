# Design decision: bundling the color-emoji font (the ~50× size tradeoff)

**Status:** accepted and shipped in v0.2.0 (2026-05-31).
**Scope:** why inkmd's pip wheel bundles a ~10 MB emoji font by default,
why that was the right call for the default tier, and how the architecture
is deliberately cut so a font-less "lite" distribution is a clean lift
later. Written at decision time so the rationale (and the still-unproven
parts) survive for a future `inkmd-lite` build and a possible blog post.

> This is a *rationale* record, not a how-to and not a roadmap commitment.
> `inkmd-lite` is **not** scheduled; it comes only once the underlying
> architecture is otherwise complete. This doc exists so that whenever it
> happens, the reasoning is on hand rather than reconstructed cold.

## Context

v0.2 added color emoji. Before it, every emoji rendered as `?` — the single
most "this tool is broken" artefact a new user hit when they pasted a README
into inkmd. Fixing it well meant shipping actual glyph data: inkmd has no
system-font lookup (that would break determinism and the "runs anywhere"
promise), so the only way emoji render identically everywhere is to carry
the font itself.

The font is Google's Noto Color Emoji, bundled unmodified (SIL OFL 1.1):

| Artefact | Size | Note |
|----------|------|------|
| `NotoColorEmoji.ttf` (raw) | ~10.67 MB | the bundled file |
| inkmd **0.1.0** wheel (pre-emoji) | ~114 KB | baseline |
| inkmd **0.2.0** wheel (font bundled) | ~10.1 MB | font compresses slightly in the wheel |
| inkmd **zipapp** (`inkmd.pyz`, font-less) | ~453 KB | the existing featherweight tier |

So the pip wheel grew roughly **50–90×** depending on which baseline you
cite (≈88× vs the 0.1.0 wheel; "~50×" is the conservative round number).
That is a large, deliberate increase, and the decision was not automatic.

## The decision

**Bundle the full font in the default pip install.** Do *not* subset it, do
*not* make emoji a `pip install inkmd[emoji]` extra, do *not* fetch it at
runtime.

## Why — the reasoning, in order of weight

### 1. The default tier optimises for "it just works," not for a metric the median user never feels.

The person who runs `pip install inkmd` wants their document to render
correctly. They do not, in that moment, care about 10 MB on disk — it is
downloaded once, costs nothing per render, and is invisible after install.
"Install size" is an abstract number; "my emoji rendered as `?`" is a
concrete, felt failure. Optimising the default for the abstract metric at
the expense of the felt experience is the wrong trade for the *median*
user. The size-sensitive user is real but is a **different, identifiable
audience** with a **different artefact** (the zipapp today, `inkmd-lite`
later) — so this is segmentation, not compromise.

### 2. Subsetting the font would ring-fence the capability for no real gain.

A subset (only the "common" emoji) trades a one-time size cost for a
permanent capability cliff: the day a user needs an emoji outside the
subset, it silently fails, and the failure is invisible at build time.
Shipping the *whole, unmodified* font means "if it's an emoji, it renders"
— no curation, no cliff, and it keeps us honest to inkmd's consistency
principle ("what GitHub showed you is what you get"). The full font is also
the OFL-clean choice: shipping it unmodified sidesteps any subsetting /
derivative-work questions entirely.

### 3. An `[emoji]` extra or a runtime download would break inkmd's core promises.

- A `pip install inkmd[emoji]` extra makes the *default* install render
  emoji as text — i.e. the `?`-class wince returns for anyone who didn't
  read the install docs. The whole point was to kill that on the happy path.
- A runtime/first-use download breaks "zero network by default" and
  "runs anywhere Python runs" (offline, locked-down CI, air-gapped) — the
  exact environments inkmd exists to serve. It also breaks determinism if
  the fetched asset ever changes.

So the only options that preserve the promises are "bundle it" or "don't
have emoji." Given emoji was the headline fix, "bundle it" wins.

### 4. — and the decision is **reversible**, which is what made the cost acceptable.

This is the load-bearing point, and the reason a ~50× increase did not
require agonising. The cost is large but the decision is a **two-way door**:
the architecture is cut so the font can be removed later *without disturbing
anything else*. We were bold on the default precisely *because* we had made
walking it back cheap. (See "The reversibility seams" below for the exact
cut points.) A large irreversible cost would have demanded a much higher bar;
a large *reversible* one only has to be right for the median user today.

## Alternatives considered and rejected

| Alternative | Rejected because |
|-------------|------------------|
| Subset the font to "common" emoji | Permanent capability cliff, invisible failures, subsetting/derivative-work friction. |
| `pip install inkmd[emoji]` extra | Default install regresses to the `?` wince; defeats the headline fix. |
| Runtime / first-use font download | Breaks zero-network, offline, determinism, "runs anywhere." |
| COLRv1 vector emoji instead of CBDT bitmaps | Far harder to implement in a hand-rolled reader; the CBDT→PNG→XObject path reuses the existing image pipeline. (See `emoji-rendering-plan.md`.) Size is comparable anyway. |
| Don't ship emoji at all | The `?` artefact was the single biggest "looks broken" signal for new users. |

## The reversibility seams (where the architecture is cut for a future lite build)

These are the concrete facts that make the "lite is a clean lift" claim
plausible. They exist **today**, in shipped code:

1. **A single font-presence gate.** `emoji._emoji_font_path()` returns
   `None` when the font file is absent (`os.path.isfile` check) *or* when
   `INKMD_NO_EMOJI` is set. Nothing else in the codebase reaches for the
   font directly.
2. **The font-absent path is the same as the always-supported fallback
   path.** When `emoji_available()` is `False`, `split_text_into_runs`
   applies the `emoji_fallback` policy — `"name"` (default → `[rocket]`-style
   labels) or `"drop"` — via a `ContextVar`. This path is fully exercised by
   the test suite (it is the zipapp's behaviour), so font-less is not an
   untested mode; it is a first-class, tested tier.
3. **A working font-less artefact already ships.** The zipapp build
   (`scripts/build_zipapp.py`) omits the font with one line —
   `shutil.ignore_patterns("assets")` — and is the ~453 KB `inkmd.pyz`.
   So "inkmd without the font" is not hypothetical; it exists and runs.
4. **Packaging is the only thing a lite *wheel* would change.** The font is
   included in the wheel solely via
   `[tool.setuptools.package-data] inkmd = ["assets/emoji/NotoColorEmoji.ttf", ...]`
   in `pyproject.toml`. A no-font wheel is a packaging variant, not a code
   change.

## What is still a PREDICTION (do not present as fact until lite is built)

The claim "extracting `inkmd-lite` will be an easy lift" is **designed to be
true** but has **not been demonstrated** — `inkmd-lite` does not exist yet.
What is genuinely proven today is only the *runtime* font-absent behaviour
(seams 1–3 above). What remains unproven, and must be checked when lite is
actually built:

- **The packaging story.** A no-font wheel can't just `del` a bundled data
  file — you can't ship a wheel that "removes" data the base wheel includes.
  Lite likely means a **separate distribution / fork** (a different package
  name, or a build flag that excludes the asset), not an `inkmd` variant.
  The clean shape is probably: the font-less core is the real package, and
  the font ships as a separate bundled asset the default install pulls in.
  That inversion was *not* done in v0.2 (we bundled into the one package);
  whether it's an "easy lift" or a packaging refactor is the open question.
- **Whether anything else quietly assumes the font is present.** The gate is
  clean as far as we know, but a real extraction is the only way to confirm
  no test, doc, or gallery silently depends on emoji rendering as images.

**If the lift turns out hard, that is the more interesting outcome to write
up, not a failure to hide.** The honest post is "I designed for reversibility;
here is where the design held and where it didn't" — written *after* doing the
work, never with the conclusion pre-decided.

## Cross-references

- `docs/design/emoji-rendering-plan.md` — the implementation (hand-rolled
  OpenType reader, CBDT bitmap extraction, GSUB ligatures).
- `docs/internals.md` — the "Color emoji as bitmap glyphs" write-up.
- `docs/security.md` — bundled-font posture (inert PNG data, no font program
  in output).
- `CHANGELOG.md` `[0.2.0]` — the user-facing summary.
