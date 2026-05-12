# inkmd conformance

> Last measured at commit `376602c`, end of Phase 2 hardening pass.
> Re-run any time with `python tests/conformance/run_commonmark.py`
> and `python tests/conformance/run_gfm.py --extensions-only`. Both
> harnesses live in `tests/conformance/` and accept `--verbose` or
> `--section <name>` for drilldown.

## Headline numbers

| Spec | Version | Pass | Total | Rate |
|------|---------|-----:|------:|-----:|
| CommonMark | 0.31.2 | 394 | 652 | 60.4% |
| GFM extensions (additive only) | 0.29 | 17 | 28 | 60.7% |

Up from the first-measurement baseline (334 / 652 = 51.2%; 9 / 28 =
32.1%) via the Phase 2 cheap-fix pass: +60 CommonMark tests, +8 GFM
extension tests. The fixes are visible in git history between
`107f28d` (first measurement commit) and `376602c` (end of Phase 2).

The remaining gap to 100% is now dominated by **deliberate v0.1
omissions** and **features tracked for v0.2**, not by triageable bugs
in features we claim. Phase 2 closed the cheap-bug bucket; what is
left needs feature-level v0.2 work, not corrective edits.

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
| ATX headings | 17 | 18 | 94.4% | claimed, mostly OK |
| Autolinks | 17 | 19 | 89.5% | claimed, mostly OK |
| Backslash escapes | 8 | 13 | 61.5% | claimed, partial |
| Blank lines | 1 | 1 | 100.0% | claimed, OK |
| Block quotes | 16 | 25 | 64.0% | claimed, partial |
| Code spans | 17 | 22 | 77.3% | claimed, mostly OK |
| Emphasis and strong emphasis | 128 | 132 | 97.0% | claimed, mostly OK |
| Entity and numeric character references | 14 | 17 | 82.4% | implemented Phase 2 |
| Fenced code blocks | 28 | 29 | 96.6% | claimed, mostly OK |
| HTML blocks | 0 | 44 | 0.0% | deliberate v0.1 omission |
| Hard line breaks | 5 | 15 | 33.3% | v0.2 — needs HardBreak AST node |
| Images | 1 | 22 | 4.5% | v0.2 |
| Indented code blocks | 2 | 12 | 16.7% | v0.2 — parser priority issue |
| Inlines | 1 | 1 | 100.0% | claimed, OK |
| Link reference definitions | 5 | 27 | 18.5% | v0.2 |
| Links | 37 | 90 | 41.1% | mixed; many depend on reference links |
| List items | 22 | 48 | 45.8% | claimed, partial |
| Lists | 12 | 26 | 46.2% | claimed, partial |
| Paragraphs | 6 | 8 | 75.0% | claimed, mostly OK |
| Precedence | 1 | 1 | 100.0% | claimed, OK |
| Raw HTML | 7 | 20 | 35.0% | deliberate v0.1 omission |
| Setext headings | 24 | 27 | 88.9% | claimed, mostly OK |
| Soft line breaks | 2 | 2 | 100.0% | implemented Phase 2 |
| Tabs | 4 | 11 | 36.4% | coupled with indented code |
| Textual content | 3 | 3 | 100.0% | claimed, OK |
| Thematic breaks | 16 | 19 | 84.2% | claimed, mostly OK |

### What changed in Phase 2

Eight focused parser fixes lifted the score from 334/652 to 394/652:

1. **AutoLink preserves source text** (commit `f390428`) — bare GFM
   autolinks render the original literal text in PDF and HTML, not
   the resolved URL with prefix. +2 CommonMark, +7 GFM extensions.
2. **Soft line breaks preserved** (commit `798660d`) — `\n` inside a
   paragraph survives in the AST instead of being collapsed to space
   at parse time. +32 CommonMark, distributed across Emphasis,
   Setext, Paragraphs, ATX headings, and Block quotes.
3. **Single-tilde strikethrough** (commit `b0baeca`) — `~text~`
   accepted alongside `~~text~~`, matching cmark-gfm. +1 GFM.
4. **Unicode P/S flanking** (commit `ea86dd5`) — emphasis flanking
   classifier extended to Unicode general categories P (punctuation)
   and S (symbols), so currency symbols correctly count as
   punctuation. +1 CommonMark.
5. **HTML5 entity decoding** (commit `f49d950`) — `&amp;`, `&#42;`,
   `&#x22;` and the full HTML5 named-entity set decode in inline
   text, link destinations, link titles, and code fence info
   strings. +12 CommonMark.
6. **Multi-backtick code spans** (commit `5783b70`) — code spans
   open with a run of N backticks and close with the next run of
   exactly N; internal newlines collapse to spaces; one leading and
   trailing space stripped together. +12 CommonMark.
7. **Backslash escapes in out-of-band contexts** (commit `376602c`)
   — link destinations, titles, and fence info strings now decode
   backslash escapes alongside entity references in one pass.
   +1 CommonMark.

### What remains, classified

**Deliberate v0.1 omissions** (89 tests):

- HTML blocks 0/44, Raw HTML 13/20 (only the escaped-text cases
  pass). Documented as "not planned in v0.1; v0.2 may add a curated
  safe subset" in the README. See task #34 for the design decision.

**v0.2 features already on the roadmap** (~110 tests):

- Images 1/22 — needs PNG/JPEG decoding and embedding.
- Link reference definitions 5/27 — needs ref table + back-reference
  resolution; also causes a chunk of Links failures.
- Hard line breaks 5/15 — needs HardBreak AST node and matching
  PDF render behaviour.
- Indented code blocks 2/12 — needs parser priority refactor that
  also affects Tabs (4/11) and a couple of List item edges.
- Task lists 0/2 in GFM extensions — small parser change.

**Real bugs that are not cheap** (~60 tests):

- Block quote edge cases (16/25): lazy continuation, blank-line
  semantics, embedded-list interactions.
- List and List-item edges (34/74 combined): tight/loose detection
  ambiguity, marker-after-content, multi-paragraph items.
- Some Link edges (37/90) that are real parser bugs, not reference-
  link blockers.

These are not "fix in 50 lines" — they need careful spec-following
and good regression coverage, which puts them in v0.2 territory.

## GFM extensions 0.29 — section breakdown

Restricted to the 28 examples in extension-specific sections.

| Section | Pass | Total | Rate |
|---------|-----:|------:|-----:|
| Tables (extension) | 6 | 8 | 75.0% |
| Task list items (extension) | 0 | 2 | 0.0% |
| Strikethrough (extension) | 3 | 3 | 100.0% |
| Autolinks (extension) | 8 | 14 | 57.1% |
| Disallowed Raw HTML (extension) | 0 | 1 | 0.0% |

### Failure classes (GFM)

- **Tables 6/8**: 2 failures involve table termination at a blank
  line followed by paragraph resumption. Minor.
- **Task lists 0/2**: v0.2 feature, on the roadmap.
- **Autolinks extension 8/14**: 6 remaining failures are real parser
  gaps — `mailto:` and `xmpp:` scheme detection in bare form without
  angle brackets, plus trailing-character trimming around bare-host
  patterns. Tractable in v0.2.
- **Disallowed Raw HTML 0/1**: depends on raw HTML passthrough,
  which we don't implement in v0.1.

## Reproducing

```sh
python tests/conformance/run_commonmark.py
python tests/conformance/run_gfm.py --extensions-only

# Drill into a single section
python tests/conformance/run_commonmark.py --section 'Code spans' --verbose

# Machine-readable
python tests/conformance/run_commonmark.py --json
```

The harness exits 0 if every test passes and 1 otherwise.

## What 60% means

The Phase 2 number to grasp is not "60%". It is that the cheap-bug
class has been emptied. If a future contribution wants to lift the
spec score, the path now is **feature work**: implement reference
links, images, hard line breaks, the indented-code-block priority
refactor. Each of those is a focused chunk that lifts one section
to near 100%. The parser is no longer leaking conformance through
small fixable bugs.
