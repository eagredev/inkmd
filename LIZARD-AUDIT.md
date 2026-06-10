# Cyclomatic complexity audit, v0.3

> **Update 2026-06-10, re-measured at v0.5.0** (same command, same exclusion):
> 338 functions, 8,238 NLOC, average CCN 7.0 (was 7.5), 35 functions over the
> CCN-15 warn threshold (was 27). The growth is accounted for: the refactored
> `feed` is gone from the list and its named phase methods now appear
> individually (`_consume_open_container` 49, `_apply_list_walk` 45); the v0.4
> font work added the TrueType glyph parsers (`_parse_simple_glyph` 27,
> `_parse_composite_glyph` 18); and v0.5's pagination and wide-table fitting
> moved `paginate_runs` from 58 to 64 (269 to 535 NLOC, now carrying forced
> breaks and oversized-group slicing), `_render_table` from 25 to 30 (with a
> nested `emit_block` helper at 21), and `styled_pdf` from 26 to 37 (page
> geometry threading). `paginate_runs` remains the standing refactor
> candidate. Safety net at measurement: 1,177 tests across 49 files, both
> conformance suites, and the byte-for-byte corpus baseline.

> **Update 2026-06-07:** `_BlockParser.feed` has since been refactored from CCN
> 145 to CCN 2, split into a short driver plus named phase methods
> (open-container consumption, document-level openers, list-stack walk, post-walk
> routing). Behavior was preserved: the full test suite, both conformance suites,
> and a byte-for-byte render check over a broad document corpus were identical
> before and after. The `feed` outlier described below is therefore historical;
> the secondary candidates (`paginate_runs`, `_render_table`) were assessed and
> left as-is (their complexity is inherent to pagination / column-fitting and
> they are already internally decomposed). The body below is kept as the
> pre-refactor receipt.

Run on `2026-06-05` with `lizard src/inkmd/ -x "*/_kerning_data.py" -C 15`,
re-measured after the v0.3 conformance push (which took the parser from ~3,250 to
4,207 lines on the way to 100% CommonMark + GFM-extension conformance). This supersedes the
v0.1 audit; the intent is unchanged: record what the audit found, what was left
alone, and why, so anyone running lizard fresh has a receipt.

## Headline

- 14 files, 265 functions, 6,768 NLOC (the generated `_kerning_data.py` table is
  excluded, as in every run of this audit).
- Average function CCN: 7.5. Average NLOC: 21.5.
- 27 functions exceed the CCN-15 warn threshold.
- The distribution is healthy at the bottom and has one clear outlier at the top.
  Most warnings are spec-driven parsing functions in the CCN 16 to 26 band; the
  long tail above that is `_tokenise` (48), `_try_parse_link_ref_def` (54),
  `_try_html_tag` (56), `paginate_runs` (58), and one genuine outlier,
  `_BlockParser.feed` at **145**.
- 823 tests across 35 files. Coverage is the load-bearing safety net here, not
  function-level simplicity.

## Warnings at a glance

| CCN | NLOC | Function | File | Disposition |
|----:|-----:|----------|------|-------------|
| 145 | 349 | `feed` | `parser.py` | **Primary refactor candidate** (see below) |
| 58 | 269 | `paginate_runs` | `layout.py` | **Refactor candidate**: central pagination state machine |
| 56 | 92 | `_try_html_tag` | `parser.py` | Left as-is: enumerates the CommonMark §6.6 inline-HTML shapes |
| 54 | 109 | `_try_parse_link_ref_def` | `parser.py` | Left as-is: the multi-line link-ref-def grammar |
| 48 | 142 | `_tokenise` | `parser.py` | Left as-is: inline-token dispatch |
| 26 | 105 | `styled_pdf` | `pdf.py` | Left as-is: PDF object assembly |
| 26 | 60 | `_handle_content_line` | `parser.py` | Left as-is: post-stack-walk block routing |
| 26 | 51 | `_try_link_body` | `parser.py` | Left as-is: bracket/precedence link rules |
| 25 | 105 | `_render_table` | `render.py` | **Refactor candidate**: column-layout state machine |
| 25 | 38 | `_html_block_start_type` | `parser.py` | Left as-is: the seven §4.6 start conditions |
| 24 | 87 | `_try_marker` | `parser.py` | Left as-is: list-marker disambiguation |
| 24 | 80 | `_scan_html` | `html_filter.py` | Left as-is: inline-HTML allow-list scan |
| 24 | 76 | `_render_inline` | `render.py` | Left as-is: inline-node dispatch |
| 24 | 41 | `_open_tag_attrs` | `html_filter.py` | Left as-is: HTML attribute parse |
| 21 | 46 | `_resolve_sequence` | `emoji.py` | Left as-is: emoji-cluster resolution |
| 21 | 31 | `_shrink_to_budget` | `render.py` | Left as-is: numerical iteration |
| 20 | 67 | `_resolve_emphasis` | `parser.py` | Left as-is: CommonMark §6.2 algorithm |
| 20 | 45 | `_add_content_line` | `parser.py` | Left as-is: marker's-first-content routing |
| 19 | 49 | `_parse_link_url` | `parser.py` | Left as-is: bracketed-or-bare URL form |
| 19 | 25 | `_scan_url_body` | `parser.py` | Left as-is: RFC-3986 char-by-char scan |
| 18 | 32 | `_try_entity_ref` | `parser.py` | Left as-is: HTML entity / numeric refs |
| 17 | 82 | `_scan_link_references` | `parser.py` | Left as-is: document-wide def pre-scan |
| 17 | 55 | `split_text_into_runs` | `emoji.py` | Left as-is: emoji splitter |
| 17 | 27 | `_scan_bare_host_with_path` | `parser.py` | Left as-is: GFM autolink rules |
| 17 | 23 | `_scan_email` | `parser.py` | Left as-is: email scan |
| 16 | 50 | `_png_xobject_pieces` | `pdf.py` | Left as-is: PNG chunk assembly |
| 16 | 35 | `_try_bare_autolink` | `parser.py` | Left as-is: GFM bare-autolink entry |

## The `feed` outlier, honestly

`_BlockParser.feed` is the block-level dispatch: for every input line it runs the
fenced-code state, the document-level and per-item HTML-block states, the table
state, the blockquote and lazy-continuation logic, the list-stack walk (continue
vs. sibling vs. break-out, with the per-item indent and 4-space-marker rules),
and the post-walk routing into indented code, HTML blocks, or normal content. The
v0.3 conformance work added most of those branches inline, and at CCN 145 it is
now well past the density where "one coherent state machine" is a sufficient
defence. It is the single standing refactor candidate.

The natural split, when it is done, is along the seams the function already has:
lift the **container-prefix consumption** (fence / HTML / table / quote verbatim
states) into one phase, the **list-stack walk** (the continue/sibling/break-out
decision and the lazy-continuation intercept) into a second, and the **post-walk
content routing** into a third, with `feed` reduced to calling them in order.
Each phase has a clear input and output and is exercised by the existing tests,
so the refactor is mechanical rather than risky - it was deferred during the
conformance push specifically to avoid churning the dispatch while correctness
was still moving, not because the split is hard.

This is recorded as a deferred item rather than done here because the audit's job
is to measure and disclose, and a 145-to-N refactor deserves its own change with
its own before/after run, not a drive-by inside an audit refresh.

## Why most of the rest was left alone

Every other warning falls into one of two categories, unchanged from the v0.1
audit's reasoning:

1. **Spec-driven parsing.** The CCN is high because the spec is branchy, not
   because the code is poorly structured. `_try_html_tag` walks the CommonMark
   §6.6 inline-HTML shapes; `_resolve_emphasis` is a faithful translation of
   `process_emphasis` from §6.2; `_try_parse_link_ref_def` encodes the multi-line
   definition grammar. Splitting these scatters spec rules across helpers and
   obscures the correspondence with the spec, which is a net negative.
2. **Central state machines.** `paginate_runs` and `_render_table` are each one
   coherent state machine whose branches are real cases. They are flagged as
   refactor candidates (as in v0.1) but are far below `feed` in urgency.

## Where the safety net actually lives

inkmd ships 823 tests across 35 files, plus the full CommonMark 0.31.2 (652) and
GFM-extension (28) spec suites at 100%. The high-CCN functions are exactly the
ones with the densest test coverage: the conformance harness exercises every
branch of `feed`, `_tokenise`, `_try_html_tag`, and the link/marker scanners
against the spec's own examples. Cyclomatic complexity measures the number of
independent paths; the spec suites are, by construction, a near-exhaustive set of
inputs that drive those paths. That is the trade inkmd makes deliberately: a few
branchy functions that are completely pinned by tests, rather than many small
functions whose interactions are pinned only by end-to-end tests.
