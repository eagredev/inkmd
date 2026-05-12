# Cyclomatic complexity audit — v0.1

Run on `2026-05-12` with `lizard src/inkmd/ -x "*/_kerning_data.py" -C 15`. This is the formal pre-v0.1 audit. The intent is to record what the audit found, what was left alone, and *why*, so that future contributors (or future me) running lizard fresh have a receipt.

## Headline

- 9 files, 118 functions, 2,952 NLOC.
- Average function CCN: 6.2. Average NLOC: 19.3.
- 12 functions exceed the CCN-15 threshold; none exceed CCN 35.
- 495 tests passing across 23 files. Coverage is the load-bearing safety net here, not function-level simplicity.

## Warnings at a glance

| CCN | NLOC | Function | File | Disposition |
|-----|------|----------|------|-------------|
| 34 | 160 | `paginate_runs` | `layout.py` | **Deferred (v0.2)** — central state machine |
| 29 | 57 | `_try_inline_link` | `parser.py` | Left as-is — six numbered spec steps |
| 28 | 82 | `feed` | `parser.py` | Left as-is — block-parser dispatch |
| 26 | 105 | `_render_table` | `render.py` | **Deferred (v0.2)** — column-layout state machine |
| 22 | 31 | `_scan_url_body` | `parser.py` | Left as-is — RFC-3986 char-by-char scan |
| 21 | 32 | `_shrink_to_budget` | `render.py` | Left as-is — numerical iteration |
| 21 | 70 | `_tokenise` | `parser.py` | Left as-is — inline-token dispatch |
| 18 | 62 | `_resolve_emphasis` | `parser.py` | Left as-is — CommonMark §6.2 algorithm |
| 18 | 43 | `_try_marker` | `parser.py` | Left as-is — list-marker disambiguation |
| 17 | 27 | `_scan_bare_host_with_path` | `parser.py` | Left as-is — GFM autolink rules |
| 17 | 24 | `_scan_email` | `parser.py` | Left as-is — email scan |
| 17 | 41 | `_parse_link_url` | `parser.py` | Left as-is — bracketed-or-bare URL form |

## Why nothing was refactored

Every warning in the table falls into one of two categories:

1. **Spec-driven parsing.** The CCN is high because the spec is branchy, not because the code is poorly structured. `_try_inline_link` walks the six numbered steps of CommonMark §6.6; `_scan_url_body` enforces GFM's balanced-paren rule plus trailing-punctuation stripping; `_resolve_emphasis` is a faithful translation of `process_emphasis` from CommonMark §6.2. Splitting these into helpers would scatter rules across multiple files and obscure the correspondence with the spec — net negative for maintainability.
2. **Central state machines.** `paginate_runs`, `feed`, and `_render_table` are each one coherent state machine. Each branch is a real case (table block vs. preserve-lines code block vs. wrapped-text paragraph; or inside-fence vs. inside-table vs. blockquote vs. list-marker vs. paragraph). The branches share enough state that extracting helpers would require passing many parameters — the cognitive load of the helpers' signatures matches the cognitive load of the inline branches.

Crucially: none of these functions are at CCN 40+. TORCH cleanups have surfaced CCN 60–90 functions where extraction was an unambiguous win. inkmd's worst function is CCN 34 in 160 NLOC — that's the **density** of a branchy spec function, not the **disorder** of code that grew incrementally.

## Where the safety net actually lives

inkmd ships 495 tests across 23 files. Coverage exercises:

- Every CommonMark inline rule (test_commonmark_inline.py + test_inline_parser.py): 80+ cases for emphasis flanking, rule of 3, intraword underscore, backslash escapes.
- Every supported block: headings, lists (tight/loose, nested, ordered/unordered, mixed-marker), blockquotes (nested, multi-paragraph, embedded code), fenced code (info-string, soft-wrap, language tag), GFM tables (alignments, narrow columns, header-only, escaped-pipe), inline + autolinks (URL/www/email/bare-host).
- Every render decision: link colour/underline/annotation, blockquote rules stacked side-by-side, table grid + header tint, code-block background tint + soft-wrap, thematic break shapes, strikethrough bars.
- End-to-end PDF validity (`%PDF-1.4` prefix, `%%EOF` suffix, `qpdf --check` clean on every torture-test render).
- CLI entrypoint via subprocess (test_cli.py).

The combination — high test count, byte-deterministic output, every public API tested end-to-end — is what makes shipping CCN-34 functions safe. If we couldn't refactor them later without breaking output, we'd have a problem. We can; the tests pin behaviour.

## Deferred refactors (v0.2)

Two functions are noted as future-refactor candidates rather than v0.1 work:

### `paginate_runs` (`layout.py`, CCN 34, 160 NLOC)

The body has three top-level branches: prepositioned blocks (tables), preserve-lines (code), and wrapped-runs (paragraphs/lists/blockquotes). Each branch is ~50 lines and has its own page-break logic. Splitting into three top-level helpers (`_paginate_prepositioned`, `_paginate_preserved`, `_paginate_wrapped`) plus a shared `_advance_page` state would reduce the top-level CCN substantially and make the three placement strategies independently readable. Risk: page-break state (y_cursor, current_lines, current_shapes, current_annotations) is shared mutable state; extracting requires either a state object or accepting that helpers will mutate-by-reference. Not v0.1.

### `_render_table` (`render.py`, CCN 26, 105 NLOC)

Computes natural widths, per-column min widths (widest-token-width guard), then either uses naturals directly or runs `_shrink_to_budget`, then lays out cell-by-cell with alignment. Splitting into `_table_widths(rows, cols, family)` and `_lay_out_cells(rows, widths, alignments)` would isolate the width-computation strategy from the placement loop. Risk lower than `paginate_runs` (no shared cross-call state). Worth doing alongside table-page-splitting work, which is also v0.2.

## How to re-run

```sh
.venv/bin/lizard src/inkmd/ -x "*/_kerning_data.py" -C 15
```

Threshold rationale: 15 is lizard's default warn level and matches the threshold TORCH uses. Functions between 15 and 25 are judgement calls; ≥ 30 is a red flag worth investigating.
