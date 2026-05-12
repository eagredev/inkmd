# inkmd conformance

> Measured at v0.1.0 (commit `3de56d2`). Re-run any time with
> `python tests/conformance/run_commonmark.py` and
> `python tests/conformance/run_gfm.py --extensions-only`. Both
> harnesses live in `tests/conformance/` and accept `--verbose` or
> `--section <name>` for drilldown.

## Headline numbers

| Spec | Version | Pass | Total | Rate |
|------|---------|-----:|------:|-----:|
| CommonMark | 0.31.2 | 334 | 652 | 51.2% |
| GFM extensions (additive only) | 0.29 | 9 | 28 | 32.1% |

These are first-measurement numbers. v0.1 was developed against a
hand-written test suite (501 unit tests across 24 files), not against
the official spec corpora. We measured the spec pass rate openly
for the first time at this commit; Phase 2 of the v0.2 roadmap is
to triage every failing test and lift the rate as far as feasible
without regressing existing behaviour.

For the v0.1 release we publish these numbers honestly. Trying to
hide them would be worse than reporting them. The interesting
content is **where** we fail.

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

## CommonMark 0.31.2 — section breakdown

| Section | Pass | Total | Rate | Status |
|---------|-----:|------:|-----:|--------|
| ATX headings | 16 | 18 | 88.9% | claimed, mostly OK |
| Autolinks | 15 | 19 | 78.9% | claimed, mostly OK |
| Backslash escapes | 5 | 13 | 38.5% | claimed, partial |
| Blank lines | 1 | 1 | 100.0% | claimed, OK |
| Block quotes | 12 | 25 | 48.0% | claimed, partial |
| Code spans | 9 | 22 | 40.9% | claimed, partial |
| Emphasis and strong emphasis | 122 | 132 | 92.4% | claimed, mostly OK |
| Entity and numeric character references | 3 | 17 | 17.6% | not claimed |
| Fenced code blocks | 25 | 29 | 86.2% | claimed, mostly OK |
| HTML blocks | 0 | 44 | 0.0% | not claimed in v0.1 |
| Hard line breaks | 5 | 15 | 33.3% | claimed, partial |
| Images | 1 | 22 | 4.5% | v0.2 |
| Indented code blocks | 1 | 12 | 8.3% | claimed, broken |
| Inlines | 1 | 1 | 100.0% | claimed, OK |
| Link reference definitions | 4 | 27 | 14.8% | v0.2 |
| Links | 34 | 90 | 37.8% | claimed, partial |
| List items | 22 | 48 | 45.8% | claimed, partial |
| Lists | 12 | 26 | 46.2% | claimed, partial |
| Paragraphs | 2 | 8 | 25.0% | claimed, partial |
| Precedence | 1 | 1 | 100.0% | claimed, OK |
| Raw HTML | 6 | 20 | 30.0% | not claimed in v0.1 |
| Setext headings | 16 | 27 | 59.3% | claimed, partial |
| Soft line breaks | 0 | 2 | 0.0% | parser bug |
| Tabs | 4 | 11 | 36.4% | claimed, partial |
| Textual content | 3 | 3 | 100.0% | claimed, OK |
| Thematic breaks | 14 | 19 | 73.7% | claimed, mostly OK |

### Failure classes

**Deliberate v0.1 omissions** (89 tests total):

- HTML blocks: 0/44. The README documents `inkmd` as markdown-to-PDF,
  not HTML-to-PDF; HTML passthrough is under design for v0.2 and may
  ship as a curated safe subset rather than full CommonMark
  passthrough.
- Raw HTML: 6/20. Same category as HTML blocks; the 6 passing
  cases are ones where we correctly *escape* the HTML rather than
  passing it through.
- Entity references: 3/17. We don't decode `&amp;`, `&#33;`,
  `&#x22;` etc. into their literal characters. Cheap to add in v0.2.

**v0.2 features already on the roadmap** (49 tests total):

- Images: 1/22. The 1 pass is an edge case where the image source
  contains a malformed `![` that we correctly leave as text.
- Link reference definitions: 4/27. The 4 passes are degenerate
  cases where the reference def looks enough like a paragraph that
  our paragraph handler produces the same HTML.

**Real parser bugs** (the interesting category — fixing these
should lift the headline number significantly):

- **Soft line break preservation**: 0/2 in the dedicated section,
  but the underlying behaviour (collapsing `\n` to a space inside a
  paragraph instead of preserving the newline) accounts for at
  least a dozen failures across Paragraphs, Emphasis, ATX headings,
  and Setext headings. Single highest-leverage fix.
- **Indented code blocks**: 1/12. We have the parser; it's not being
  triggered at the right priority versus paragraph lazy continuation.
  Affects Tabs and ATX headings tests too (a 4-space-indented line
  should become a code block, not be absorbed into a paragraph).
- **Code span tokenisation**: 9/22. Multi-backtick spans (`` ``foo`` ``)
  and code spans with leading/trailing space handling are
  inconsistent.
- **Link parsing**: 34/90. Several link edge cases around bracket
  nesting, link-text-with-formatting, and reference vs. inline
  ambiguity.
- **Currency-symbol flanking**: a Unicode general-category bug where
  characters like `$`, `£`, `€` are treated differently in flanking
  rules. CommonMark §6.2 says emphasis cannot open immediately
  before or close immediately after a *punctuation* character; our
  classifier disagrees with the spec on which Unicode codepoints
  count as punctuation.

**Serialiser bugs (not parser bugs)** — the parser is correct, the
HTML output from our test harness disagrees with the spec's reference
format:

- Some link/autolink cases store the resolved URL where they should
  store the original source text. Affects ~3 CommonMark tests and
  most of the GFM autolinks-extension tests (see below).

## GFM extensions 0.29 — section breakdown

Restricted to the 28 examples in extension-specific sections.

| Section | Pass | Total | Rate |
|---------|-----:|------:|-----:|
| Tables (extension) | 6 | 8 | 75.0% |
| Task list items (extension) | 0 | 2 | 0.0% |
| Strikethrough (extension) | 2 | 3 | 66.7% |
| Autolinks (extension) | 1 | 14 | 7.1% |
| Disallowed Raw HTML (extension) | 0 | 1 | 0.0% |

### Failure classes

- **Tables 6/8**: The 2 failures involve edge cases where lazy
  table continuation should terminate at a blank line and resume as
  a paragraph. Minor.
- **Task lists 0/2**: v0.2 feature, expected.
- **Strikethrough 2/3**: GFM allows both `~~text~~` and `~text~`;
  we only accept `~~text~~`. The 1 failure is the single-tilde case.
- **Autolinks extension 1/14**: as noted above, this is primarily a
  serialiser bug. The parser correctly identifies `www.foo.com` as
  a link to `http://www.foo.com`, but our HTML serialiser emits the
  *resolved* URL as the link's display text rather than the original
  source. Fixing this would lift the section to roughly 10/14;
  remaining 4 failures are real parser gaps (`mailto:` and `xmpp:`
  scheme detection without angle brackets, plus a trailing-character
  trimming rule).
- **Disallowed Raw HTML 0/1**: depends on raw HTML passthrough,
  which we don't implement. Not applicable to v0.1.

## Reproducing

```sh
# Pull spec corpora (CommonMark JSON, GFM HTML)
curl -sL https://spec.commonmark.org/0.31.2/spec.json \
    -o tests/conformance/commonmark-0.31.2.json
curl -sL https://github.github.com/gfm/ -o /tmp/gfm.html
python tests/conformance/extract_gfm.py

# Run
python tests/conformance/run_commonmark.py
python tests/conformance/run_gfm.py --extensions-only

# Drill into a single section
python tests/conformance/run_commonmark.py --section 'Code spans' --verbose

# Machine-readable
python tests/conformance/run_commonmark.py --json
```

The harness exits 0 if every test passes and 1 otherwise, so it
can run in CI once we're closer to 100% on the categories we claim
to support.

## Why we publish these numbers at 51%

Hiding the number would be the wrong call. v0.1 was developed
against a hand-written test suite that gave us strong coverage of
the features we *use* but didn't probe the spec's edges. The
honest position is: we know where we are, we know which gaps are
deliberate (HTML passthrough), which are v0.2 (images, reference
links, task lists), and which are real bugs (soft line breaks,
indented code blocks, code spans). The Phase 2 roadmap fixes the
real-bug category before v0.2.

Anyone running these harnesses themselves will get the same
numbers we publish. The byte-for-byte determinism guarantee means
"same input, same output, every time" — including the conformance
harness output.
