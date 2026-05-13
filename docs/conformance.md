# inkmd conformance

> Last measured at commit `387122e`, end of v0.2 release prep.
> Re-run any time with `python tests/conformance/run_commonmark.py`
> and `python tests/conformance/run_gfm.py --extensions-only`. Both
> harnesses live in `tests/conformance/` and accept `--verbose` or
> `--section <name>` for drilldown.

## Headline numbers

| Spec | Version | Pass | Total | Rate |
|------|---------|-----:|------:|-----:|
| CommonMark | 0.31.2 | 554 | 652 | 85.0% |
| GFM extensions (additive only) | 0.29 | 20 | 28 | 71.4% |

Up from v0.1 (`394/652` = 60.4%; `17/28` = 60.7%) via the v0.2 work:
+160 CommonMark tests, +3 GFM extension tests. The progression is
visible in the v0.2 commits between `b12e1b0` (task lists, first
v0.2 feature commit) and `387122e` (GFM bare-URL paren handling).

The remaining gap to 100% is dominated by **block-level raw HTML**
(42 of the 98 failing tests are in the HTML blocks section, which
inkmd treats as out of scope for PDF output) and **deep list-indent
edges** (mixed-indent siblings, blockquote-inside-list-item). Both
are tracked for v0.3.

## How the harness works

inkmd's public API produces PDFs, not HTML. To compare against the
spec we serialise our AST to CommonMark reference-style HTML via
`tests/conformance/html_serialise.py`. The serialiser is not part
of the public package; it exists so we can run the spec's HTML
byte-comparison harness against our parser output.

`run_commonmark.py` runs every test in CommonMark 0.31.2 with our
parser in strict mode (`autolinks=False`). `run_gfm.py` runs the
GFM 0.29 corpus extracted from the spec page; `--extensions-only`
restricts to the additive surface (tables, autolinks extension,
strikethrough, task lists, disallowed raw HTML).

Both spec sources are committed to the repo
(`tests/conformance/commonmark-0.31.2.json` and
`tests/conformance/gfm-spec-source.html` plus the extracted
`gfm-0.29.json`), so the harness has zero network dependencies.

## CommonMark 0.31.2 — section breakdown

| Section | Pass | Total | Rate | Status |
|---------|-----:|------:|-----:|--------|
| ATX headings | 18 | 18 | 100.0% | OK |
| Autolinks | 19 | 19 | 100.0% | OK |
| Backslash escapes | 12 | 13 | 92.3% | one HTML-block-dependent edge |
| Blank lines | 1 | 1 | 100.0% | OK |
| Block quotes | 24 | 25 | 96.0% | one Setext-inside-quote edge |
| Code spans | 21 | 22 | 95.5% | one bracket-precedence edge |
| Emphasis and strong emphasis | 131 | 132 | 99.2% | one unclosed-emphasis-at-EOF edge |
| Entity and numeric character references | 16 | 17 | 94.1% | one HTML-block-dependent edge |
| Fenced code blocks | 29 | 29 | 100.0% | OK |
| HTML blocks | 2 | 44 | 4.5% | block-level HTML out of scope for PDF |
| Hard line breaks | 15 | 15 | 100.0% | OK |
| Images | 21 | 22 | 95.5% | one nested-image-in-image edge |
| Indented code blocks | 11 | 12 | 91.7% | one list-marker-detection edge |
| Inlines | 1 | 1 | 100.0% | OK |
| Link reference definitions | 25 | 27 | 92.6% | def-inside-quote + paren-form edge |
| Links | 79 | 90 | 87.8% | nested-bracket cases + HTML-tag-inhibits |
| List items | 32 | 48 | 66.7% | blockquote-inside-list (v0.3) |
| Lists | 14 | 26 | 53.8% | mixed-indent siblings (v0.3) |
| Paragraphs | 8 | 8 | 100.0% | OK |
| Precedence | 1 | 1 | 100.0% | OK |
| Raw HTML | 18 | 20 | 90.0% | HTML-comment-edge cases |
| Setext headings | 26 | 27 | 96.3% | one lazy-continuation-in-quote edge |
| Soft line breaks | 2 | 2 | 100.0% | OK |
| Tabs | 7 | 11 | 63.6% | list-aware tab indent (partial v0.3) |
| Textual content | 3 | 3 | 100.0% | OK |
| Thematic breaks | 18 | 19 | 94.7% | one thematic-break-inside-item edge |

### What changed in v0.2

The headline gains, in approximate descending order of test impact:

1. **Reference links and reference images** (commit `b2ccace`): full
   support for `[label]: url "title"` definitions plus the three
   reference forms (`[text][label]`, `[label][]`, `[label]`) and
   image variants. +64 CommonMark tests.
2. **Indented code blocks** at document level (commit `e0540b3`) and
   inside list items (commit `a9bc036`): the common README pattern
   of placing a code sample under a bullet now renders correctly.
   +26 CommonMark, +6 List items tests, gallery output corrected.
3. **Hard line breaks** (commit `f8d798a`): both the
   two-trailing-spaces form and the backslash-before-newline form
   emit hard breaks. Section to 15/15.
4. **Tab preservation in code blocks** (commit `3c48aab`): tabs are
   not expanded at parse time; the literal byte survives into code
   block content. +4 Tabs tests at document level.
5. **Conformance polish** (commit `ab1656e`): blockquote lazy
   continuation, link URL edges (`[link]()`, paren-form titles,
   multi-line URL/title), autolink email charset, URL percent-encode
   of `[` and `]`, `1.`-only ordered-marker-interrupts-paragraph.
   +15 CommonMark.
6. **Code spans + soft breaks** (commit `97f9af2`): trailing-space
   preservation on paragraph lines so end-of-paragraph code spans
   keep meaningful whitespace; soft-break strip moved to serialise
   time per spec. +3 CommonMark.
7. **Image-inside-link** (commit `a9bc036`): the
   `[![badge](badge.png)](/repo)` pattern parses correctly.
   +2 CommonMark.
8. **Image AST + PNG/JPEG embedding** (commits `7c51ff3`, `89199de`):
   AST node, parser, conformance serialiser, and the full PDF
   embedding pipeline. +14 Images tests, +inkmd renders actual
   images in PDFs.
9. **HTML passthrough Option B** (commit `8c6f0d2`): inline HTML
   recognition with a typed/promoted/dropped allow-list. Section
   to 18/20 Raw HTML; surface visible via `<sub>`, `<mark>`,
   `<u>`, `<kbd>`, etc. visual decorations.

### What remains, classified by v0.x tier

**v0.3 visual-perfection tier** (~70 tests):

- **HTML blocks 2/44**: block-level HTML (e.g. raw `<table>...</table>`
  at top level) doesn't pass through verbatim. Practical PDF impact
  is small (the text content still renders); spec-test impact is
  large (42 tests). The v0.2 framing is: "v0.2 covers what people
  actually write in markdown; raw HTML blocks are an HTML-renderer
  feature, not a markdown one."
- **Blockquote inside a list item** (~6 List items tests): `>` inside
  a list item should open a blockquote, currently renders as
  paragraph text starting with `&gt;`. Needs per-item blockquote
  state.
- **Deep mixed-indent list siblings** (~8 Lists tests): off-by-one
  indent sequences (e.g. CommonMark example 310's
  `- a\n - b\n  - c\n   - d\n  - e\n - f\n- g`) collapse to a flat
  list in spec, but inkmd produces a structurally similar nested
  list. Visually close, structurally different.
- **Tab-as-list-content-indent** (~3 Tabs tests): leading tab past
  a list item's content column. Doc-level tab indent is fixed;
  list-level needs more virtual-column accounting.

**v0.4 spec-corner tier** (~25 tests):

- Setext-inside-blockquote lazy continuation (1 test)
- Nested-image-inside-image alt text (2 tests)
- Nested bracket-pair link text (~5 tests)
- HTML-tag-inhibits-link recognition (~3 tests)
- Code-span bracket precedence (1 test)
- Various single-test edges in 90%+ sections

## GFM extensions 0.29 — section breakdown

Restricted to the 28 examples in extension-specific sections.

| Section | Pass | Total | Rate |
|---------|-----:|------:|-----:|
| Tables (extension) | 6 | 8 | 75.0% |
| Task list items (extension) | 2 | 2 | 100.0% |
| Strikethrough (extension) | 3 | 3 | 100.0% |
| Autolinks (extension) | 9 | 14 | 64.3% |
| Disallowed Raw HTML (extension) | 0 | 1 | 0.0% |

### Failure classes (GFM)

- **Tables 6/8**: two failures involve table termination at an
  unrelated paragraph immediately below the table and a malformed
  table-shape that should fall back to paragraph rendering. Both
  v0.3.
- **Autolinks extension 9/14**: five failures are around bare email
  autolinks without angle brackets (`foo@bar.baz` rendered inline),
  literal scheme prefixes (`mailto:`, `xmpp:`) in bare form, and
  trailing-character trimming for entity-like patterns. v0.3.
- **Disallowed Raw HTML 0/1**: depends on raw HTML block-level
  passthrough, which inkmd considers out of scope for PDF output.

## Reproducing

```sh
python tests/conformance/run_commonmark.py
python tests/conformance/run_gfm.py --extensions-only

# Drill into a single section
python tests/conformance/run_commonmark.py --section 'Code spans' --verbose
python tests/conformance/run_gfm.py --extensions-only --section 'Autolinks' --verbose
```

The harness is fast: full CommonMark run is sub-second on the dev
machine. No network, no compilation, just stdlib.
