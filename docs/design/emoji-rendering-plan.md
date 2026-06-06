# Color emoji rendering: implementation plan

Status: PLAN (awaiting review). Decided 2026-05-30. Escalated to v0.2.

## Goal

Render color emoji in compiled PDFs by default, hand-rolled (no third-party
libraries), keeping a featherweight opt-out. Replace the current
emoji-as-`?` artifact (`fonts.to_winansi_byte` maps unrepresentable
codepoints to `?`).

## Verified facts (from the 2026-05-30 spike)

- `NotoColorEmoji.ttf` is a single-strike **CBDT/CBLC bitmap** font
  (no `glyf`, no `COLR`). Strike ppem = 109; glyph bitmaps are **136×128px
  indexed-color PNGs with `PLTE` + `tRNS`** transparency.
- Hand-rolled parsing of the table directory, `cmap` format 12 (codepoint
  to gid), `cmap` format 14 (variation selectors), and the `CBLC`/`CBDT`
  walk to extract a glyph's PNG verbatim all work in ~120 lines, no deps.
  Extracted a valid color rocket PNG end to end.
- inkmd's PNG XObject path (`pdf.py::_png_xobject_pieces`) currently
  **rejects indexed (type 3) and RGBA (type 6)** PNGs ("pending v0.3").
  Emoji PNGs are type 3 (indexed). This is the one prerequisite subsystem.

## Architecture overview

```
parse → (text contains emoji codepoints)
render._render_inline: split a Text inline into [text Run | EmojiRun | text Run …]
        an EmojiRun carries the resolved glyph id (+ the source codepoints)
layout: an EmojiRun occupies a fixed advance box (square, ~1 em) on the line;
        measured from glyph metrics, participates in wrap like any run
pdf:    an EmojiRun emits an Image XObject placement (reusing the existing
        PNG path, now indexed+tRNS-capable) instead of a Tj/TJ text op
```

The emoji font is loaded once (lazily), parsed by the hand-rolled reader,
and glyph PNGs are extracted on demand + cached. If the font asset is
absent (the `[lite]` opt-out) or a codepoint isn't covered, the **fallback
policy** applies: textual name (default) or drop (configurable).

## Subsystem build order (each its own commit + tests)

### Phase 1: Indexed + tRNS PNG support (prerequisite, reusable)
`pdf.py`. Teach `_png_xobject_pieces` / `_image_xobject_body` to emit:
- **Indexed colour:** `/ColorSpace [/Indexed /DeviceRGB <hival> <palette-bytes>]`
  from the `PLTE` chunk; pass IDAT through with `/Predictor 15`,
  `/Colors 1`, `/BitsPerComponent <depth>` (indexed = 1 component).
- **Transparency from `tRNS`:** build a soft mask. For indexed, `tRNS`
  gives per-palette-entry alpha. Cleanest general route: emit a separate
  `/SMask` Image XObject (DeviceGray, 8bpc) whose pixels are the alpha of
  each source pixel. That requires expanding indexed pixels to alpha, which
  needs decoding IDAT (zlib inflate + PNG unfilter), a small pure-Python
  step. (Stdlib `zlib` is allowed: it ships with CPython, not a third-party
  dep.) Alternative for fully-binary transparency: color-key `/Mask` array,
  but emoji `tRNS` has partial alpha (anti-aliased edges), so `/SMask` is
  the correct choice.
- This closes the existing "indexed PNG pending v0.3" gap for ALL images,
  not just emoji.
- Tests: round-trip an indexed PNG with tRNS, assert XObject dict shape,
  assert SMask object present + correct dimensions, assert determinism.

### Phase 2: Hand-rolled OpenType reader (`src/inkmd/emoji_font.py`, new)
Pure-Python, no deps. Promote the spike to production quality:
- `class EmojiFont`: parse table directory; lazy-load `cmap` (fmt 12 + 14),
  `CBLC`/`CBDT`, `GSUB`, `hmtx`.
- `cmap_lookup(codepoint) -> gid` (fmt 12); `variation_lookup(cp, vs) -> gid`
  (fmt 14, for U+FE0F/FE0E).
- `glyph_png(gid) -> (png_bytes, metrics)` via the CBLC strike to the index
  subtable (formats 1 & 2) to CBDT (image formats 17 & 18). Cache by gid.
- Robust to absent tables / unknown formats: raise a typed error the
  caller turns into the fallback path. Never crash a compile.
- Tests: against the bundled subset font, known codepoints map to known
  gids; PNG extraction returns valid PNG signature + expected dims; metrics
  sane; missing-glyph returns None cleanly.

### Phase 3: Single-codepoint emoji rendering (end to end)
- `ast`/`render`: introduce an `EmojiRun` (or a flagged `Run`) carrying
  `codepoints: tuple[int,...]` + resolved `gid`. In `_render_inline`,
  scan `Text.content` for emoji codepoints (an emoji-range predicate +
  the font's cmap as the authority), splitting into text/emoji runs.
- `layout`: give an emoji run a fixed advance (square box ≈ font size,
  scaled from strike metrics); slots into `wrap_runs` measurement. Baseline
  alignment: emoji sit on/just above the text baseline (use bearing).
- `pdf`: an emoji run emits an Image XObject placement at the run's box
  (scale the 136×128 strike PNG to the em box via the `cm` matrix) instead
  of a text show operator. Reuse Phase-1 indexed+tRNS embedding.
- Tests: compile `"# 🚀 Launch"` and the PDF contains an image XObject + SMask,
  emoji box within margins, text around it positioned correctly, output
  deterministic. Visual check via pdftoppm.

### Phase 4: Emoji sequences via GSUB type-4 ligatures (#1 bug risk)
- `emoji_font`: parse `GSUB` into script/feature/lookup tables, then **type 4
  (ligature) lookups**. Build a ligature trie: sequence of component gids
  maps to ligature gid.
- `render`: after cmap-mapping a run of emoji codepoints to component gids,
  apply ligature substitution greedily (longest match) so ZWJ sequences
  (👨‍👩‍👧), regional-indicator flags (🇯🇵), and skin-tone modifiers (👍🏽)
  compose into their single glyph.
- Tests: 👨‍👩‍👧‍👦 / 🇯🇵 / 👍🏽 / ✅ render as ONE image each (not component
  glyphs side by side); a ZWJ sequence the subset lacks falls back per
  policy.

### Phase 5: Font subset + bundling
- Build a curated subset (~200-400 common README emoji: status, arrows,
  faces, flags, tech symbols). Generate a derived font asset OR a
  pre-extracted PNG+metadata pack (decide in Phase 5: shipping a subset
  `.ttf` triggers the OFL Reserved-Font-Name rename; shipping a pack of
  extracted PNGs + a codepoint-to-PNG index sidesteps the font-file question
  entirely and may be smaller and faster (lean toward the pack).
- Place under `src/inkmd/assets/emoji/`; include `OFL.txt`.
- `package-data` in `pyproject.toml` ships it in the default wheel.
- Tests: asset loads; subset covers the curated set; wheel-size check.

### Phase 6: Fallback policy + `[lite]` opt-out
- `fonts`/`render`: when no glyph (lite install OR uncovered codepoint),
  apply fallback. Default = **textual name** via stdlib `unicodedata.name()`,
  e.g. `[rocket]` (curate a short-name map for the ugly official names;
  fall back to a slugified `unicodedata.name`). Config flag switches to
  **drop** (zero-width).
- API: a `compile(..., emoji_fallback="name"|"drop")` kwarg (default
  "name"); the no-asset path auto-degrades to the same fallback.
- `pyproject.toml`: define `inkmd[lite]`? Actually lite = the BASE with
  the font NOT installed. Mechanism: ship the font as the default; provide
  a documented way to exclude it (an extras split where the heavy asset is
  its own package, or an env/flag that skips loading). Decide concrete
  packaging in Phase 6. The runtime already degrades gracefully, so this
  is purely a distribution detail.
- Tests: lite path (asset absent), fallback fires, no crash; "name" vs
  "drop" both correct; round-trip determinism.

### Phase 7: Docs, gallery, conformance
- Update README (emoji now render; note the bitmap/scale tradeoff + lite
  opt-out + fallback), `docs/` design note, the unicode-winansi gallery
  doc (regenerate; `07-unicode-winansi.pdf` will change), and re-render
  the real-world gallery (Ruff README's 🚀⚡ now render in color).
- Confirm CommonMark/GFM conformance unchanged (emoji is a render concern,
  not a parse one, so it should be zero movement).

## Open decisions deferred into their phases
- Phase 5: ship a subset `.ttf` (OFL rename) vs a pre-extracted PNG pack
  (likely smaller/faster, sidesteps RFN). Lean: PNG pack.
- Phase 6: exact `[lite]` packaging mechanism (extras vs separate asset
  package vs flag). Runtime degradation already handles absence.

## Risks / sharp edges (from research + spike)
1. **GSUB ligatures** (Phase 4): skip it and component glyphs render separately.
   #1 correctness risk. Test sequences early.
2. **Bitmap scaling**: scale from strike ppem (109) using glyph metrics,
   not raw PNG dims; respect bearing/advance for baseline + spacing.
3. **tRNS partial alpha**: must use `/SMask`, not binary `/Mask`, or
   anti-aliased emoji edges get hard/ugly.
4. **Determinism**: emoji XObject ordering + ids must be deterministic
   (same first-appearance scheme as existing images).
5. **License**: `OFL.txt` in wheel; if a derived `.ttf` ships, rename off
   "Noto".

## Files touched (summary)
- NEW `src/inkmd/emoji_font.py`: OpenType reader (cmap/CBLC/CBDT/GSUB).
- NEW `src/inkmd/assets/emoji/`: subset asset + OFL.txt.
- `src/inkmd/pdf.py`: indexed+tRNS PNG (Phase 1); emoji XObject placement.
- `src/inkmd/render.py`: emoji run splitting, sequence ligation, fallback.
- `src/inkmd/layout.py`: emoji run measurement/placement.
- `src/inkmd/fonts.py`: fallback (textual name) helper; stop `?`-ing emoji.
- `src/inkmd/__init__.py`: `emoji_fallback` kwarg.
- `pyproject.toml`: package-data for the asset; lite distribution.
- tests + docs/gallery as per phases.
