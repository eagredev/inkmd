# inkmd conformance

> Measured against CommonMark 0.31.2. These 100% figures are the v0.3
> release, up from 85.0% / 71.4% in the 0.2.x line. Re-run any time with
> `python tests/conformance/run_commonmark.py` and
> `python tests/conformance/run_gfm.py --extensions-only`. Both harnesses
> live in `tests/conformance/` and accept `--verbose` or `--section <name>`
> for drilldown.

## Headline numbers

| Spec | Version | Pass | Total | Rate |
|------|---------|-----:|------:|-----:|
| CommonMark | 0.31.2 | 652 | 652 | **100%** |
| GFM extensions (additive only) | 0.29 | 28 | 28 | **100%** |

**Full conformance: 652/652 CommonMark and 28/28 GFM extensions, with zero
exceptions.** Every CommonMark example and every GFM extension example passes
byte-for-byte against the reference HTML. (The GFM spec's full corpus also
includes its CommonMark-superset HTML-block cases, where raw `<script>`,
`<style>`, and `<textarea>` are passed through verbatim; inkmd escapes those
by design under its HTML security model, so the `--extensions-only` flag scopes
the GFM run to the additive extension surface.)

Up from v0.2 (`554/652` = 85.0%; `20/28` = 71.4%) via the v0.3 push:
+98 CommonMark, +8 GFM extension. The gains, by cluster: block-level
raw HTML passthrough (HTML blocks 2/44 -> 44/44, including inside list
items), the list/indent core (blockquote-in-item, mixed-indent siblings,
nested/empty markers, loose-list detection, fence-in-item, the 4-space
marker rule, per-container tab virtual-columns, lazy-continuation across
reparse boundaries), GFM tables (6/8 -> 8/8), the inline link/autolink
scanners (Links 79/90 -> 90/90, GFM autolinks 9/14 -> 14/14, Raw HTML
18/20 -> 20/20), link-reference-definitions inside blockquotes, and a unified
code-block content-newline convention (trailing blank lines inside fences).

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

## CommonMark 0.31.2 - section breakdown

| Section | Pass | Total | Rate | Status |
|---------|-----:|------:|-----:|--------|
| ATX headings | 18 | 18 | 100.0% | OK |
| Autolinks | 19 | 19 | 100.0% | OK |
| Backslash escapes | 13 | 13 | 100.0% | OK |
| Blank lines | 1 | 1 | 100.0% | OK |
| Block quotes | 25 | 25 | 100.0% | OK |
| Code spans | 22 | 22 | 100.0% | OK |
| Emphasis and strong emphasis | 132 | 132 | 100.0% | OK |
| Entity and numeric character references | 17 | 17 | 100.0% | OK |
| Fenced code blocks | 29 | 29 | 100.0% | OK |
| HTML blocks | 44 | 44 | 100.0% | OK |
| Hard line breaks | 15 | 15 | 100.0% | OK |
| Images | 22 | 22 | 100.0% | OK |
| Indented code blocks | 12 | 12 | 100.0% | OK |
| Inlines | 1 | 1 | 100.0% | OK |
| Link reference definitions | 27 | 27 | 100.0% | OK |
| Links | 90 | 90 | 100.0% | OK |
| List items | 48 | 48 | 100.0% | OK |
| Lists | 26 | 26 | 100.0% | OK |
| Paragraphs | 8 | 8 | 100.0% | OK |
| Precedence | 1 | 1 | 100.0% | OK |
| Raw HTML | 20 | 20 | 100.0% | OK |
| Setext headings | 27 | 27 | 100.0% | OK |
| Soft line breaks | 2 | 2 | 100.0% | OK |
| Tabs | 11 | 11 | 100.0% | OK |
| Textual content | 3 | 3 | 100.0% | OK |
| Thematic breaks | 19 | 19 | 100.0% | OK |

Every section is at 100%.

### What changed in v0.2

The headline gains, in approximate descending order of test impact:

1. **Reference links and reference images** (commit `5809108`): full
   support for `[label]: url "title"` definitions plus the three
   reference forms (`[text][label]`, `[label][]`, `[label]`) and
   image variants. +64 CommonMark tests.
2. **Indented code blocks** at document level (commit `ae1970d`) and
   inside list items (commit `5869edf`): the common README pattern
   of placing a code sample under a bullet now renders correctly.
   +26 CommonMark, +6 List items tests, gallery output corrected.
3. **Hard line breaks** (commit `d5d32e8`): both the
   two-trailing-spaces form and the backslash-before-newline form
   emit hard breaks. Section to 15/15.
4. **Tab preservation in code blocks** (commit `d325c01`): tabs are
   not expanded at parse time; the literal byte survives into code
   block content. +4 Tabs tests at document level.
5. **Conformance polish** (commit `9fd838b`): blockquote lazy
   continuation, link URL edges (`[link]()`, paren-form titles,
   multi-line URL/title), autolink email charset, URL percent-encode
   of `[` and `]`, `1.`-only ordered-marker-interrupts-paragraph.
   +15 CommonMark.
6. **Code spans + soft breaks** (commit `4965238`): trailing-space
   preservation on paragraph lines so end-of-paragraph code spans
   keep meaningful whitespace; soft-break strip moved to serialise
   time per spec. +3 CommonMark.
7. **Image-inside-link** (commit `5869edf`): the
   `[![badge](badge.png)](/repo)` pattern parses correctly.
   +2 CommonMark.
8. **Image AST + PNG/JPEG embedding** (commits `13b0bed`, `f12bedd`):
   AST node, parser, conformance serialiser, and the full PDF
   embedding pipeline. +14 Images tests, +inkmd renders actual
   images in PDFs.
9. **HTML passthrough Option B** (commit `bcf8802`): inline HTML
   recognition with a typed/promoted/dropped allow-list. Section
   to 18/20 Raw HTML; surface visible via `<sub>`, `<mark>`,
   `<u>`, `<kbd>`, etc. visual decorations.

## v0.3 documented exceptions (Gate-1 rule)

**There are none.** Gate 1 is met at literal 100% - all 652 CommonMark and 28
GFM-extension examples pass byte-for-byte; the documented-exception mechanism is
unused.

The v0.3 push reached this under a deliberately strict reading of the Gate-1 bar:
an exception was acceptable only if a test was *genuinely not achievable*, not
merely if the fix was large or risky. Every candidate exception was fixed:

- **Block-level tab virtual-columns** (Tabs 5/6/7) - absolute-column tab
  expansion after `>` / list markers (`_expand_leading_ws`).
- **Lazy-continuation across the reparse boundary** (Block quotes 238, Setext
  93, List items 292) - `lazy_lines` provenance threaded into the recursive
  parse, plus `_line_ends_in_open_paragraph` for nested cases.
- **The per-container mixed-indent ladder** (Lists 312/313, List items 257) -
  the 4-space-marker rule and an indented-code re-check after a list closes.
- **Link-reference definitions inside blockquotes** (Link ref defs 218) -
  prefix-stripping in the document-wide def scan.
- **HTML blocks inside list items** (HTML blocks 175) - per-item HTML-block
  state mirroring the document-level machinery.
- **Trailing blank lines inside fenced code** (Lists 318) - a unified
  code-block content-newline convention (each line terminated, EOF artifact
  dropped), shared by fenced and indented code; the render path strips the
  final terminator so PDF output is unchanged.

## GFM extensions 0.29 - section breakdown

Restricted to the 28 examples in extension-specific sections.

| Section | Pass | Total | Rate |
|---------|-----:|------:|-----:|
| Tables (extension) | 8 | 8 | 100.0% |
| Task list items (extension) | 2 | 2 | 100.0% |
| Strikethrough (extension) | 3 | 3 | 100.0% |
| Autolinks (extension) | 14 | 14 | 100.0% |
| Disallowed Raw HTML (extension) | 1 | 1 | 100.0% |

**GFM extensions: 28/28 (100%).** Tables gained column-count validation
(a header/delimiter cell-count mismatch falls back to a paragraph) and
lazy row continuation; the autolink extension gained the GFM extended-
email rule, `mailto:`/`xmpp:` bare-protocol autolinks, and entity-suffix
trimming; disallowed-raw-html rides on the block-level HTML passthrough.

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
