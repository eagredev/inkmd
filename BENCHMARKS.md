# Benchmarks

`inkmd` vs `WeasyPrint + markdown` on the same input documents.

## TL;DR

| Metric | inkmd | WeasyPrint | Ratio |
|--------|-------|------------|-------|
| Cold-start render, ~1 page | 138 ms | 731 ms | 5.3x faster |
| Cold-start render, ~11 pages | 201 ms | 1.40 s | 7.0x faster |
| Peak RSS, ~1 page | 18 MB | 65 MB | 3.6x lower |
| Peak RSS, ~11 pages | 20 MB | 122 MB | 6.2x lower |
| Install size (venv) | 22.3 MB | 74.6 MB | 3.3x smaller |
| Output size, ~1 page | 10.4 KB | 17.1 KB | inkmd 1.6x smaller |
| Output size, ~11 pages | 150.6 KB | 121.8 KB | WeasyPrint 1.24x smaller |

inkmd is 5 to 7x faster, 3 to 6x lighter on memory, and 3.3x smaller to install (22.3 MB vs 74.6 MB) while needing zero system packages. Output size goes either way depending on document size (see "Output size crossover" below).

> **Install size note:** inkmd bundles the full Noto Color Emoji font (~10 MB) so emoji render anywhere without a system font. That's the bulk of the 22.3 MB. The font-less zipapp (`inkmd.pyz`, ~170 KB) is the size-sensitive distribution. inkmd's advantage over WeasyPrint is *zero system dependencies*, not just raw size: 22.3 MB of pip-installable wheel beats 74.6 MB of wheel **plus** 350-550 MB of system packages (Pango/Cairo/GObject) that break on Alpine and Windows.

## Caveats up front

These numbers are honest but limited. Read this section before drawing conclusions.

- **One competitor only.** WeasyPrint is the closest pure-Python alternative and was the natural comparison. mdpdf (Node + headless Chrome), Pandoc + LaTeX, and others are not measured. If you care about those specifically, run the benchmark script against them.
- **One platform.** Measurements taken on a Steam Deck (SteamOS, x86_64). Results on macOS, Windows, or different Linux distros may differ by 10 to 30 percent, but the order-of-magnitude ratios should hold.
- **WeasyPrint can do more.** inkmd supports images (PNG, JPEG) and task lists; it does not yet support full Unicode (CJK, Cyrillic, etc) or horizontal fitting for very wide tables. WeasyPrint handles all of these. This is not a feature-parity comparison; it is a "for the things inkmd does, how does it compare" comparison. Use the right tool for your inputs.
- **Cold-start dominates for short jobs.** If you render hundreds of documents in one Python process, in-process steady-state numbers matter more. If you invoke a CLI once per document in CI, cold-start is what you feel.
- **Different markdown frontends.** WeasyPrint uses `markdown` (Python-Markdown) with `tables` and `fenced_code` extensions to produce HTML, which WeasyPrint then renders. inkmd compiles markdown directly. The pipeline difference is part of what makes inkmd faster, not an unfair advantage.

## Methodology

The script lives at `scripts/bench.py` in this repo. Run it yourself:

```sh
python scripts/bench.py                  # text output (default)
python scripts/bench.py --output table   # markdown table
```

On first run it creates two virtualenvs under `bench-venvs/`: one with just `inkmd`, one with `weasyprint` and `markdown`. Subsequent runs reuse the venvs.

For each input document the script runs each tool 5 times via subprocess (warming filesystem caches once before measuring), records wall time and peak RSS per run, and reports the median.

### Inputs

Two real documents from the repo:

- **Small**: `examples/hero-sample.md`, around 1 KB of markdown that produces a single-page PDF with headings, mixed inline formatting, a small table, a blockquote, a code block, and an autolinked URL.
- **Medium**: `examples/torture-test.md`, around 15 KB of markdown that produces an 11-page PDF exercising every supported feature including nested lists, multi-paragraph blockquotes, fenced code blocks, GFM tables with alignments, and several link styles.

### Measurements

- **Wall time** via `time.perf_counter()` around the subprocess call. Includes Python interpreter startup, package import, and PDF write.
- **Peak RSS** via a watcher thread polling `/proc/<pid>/status` every 5 ms while the child process runs.
- **Install size** via recursive `stat().st_size` summed over the venv directory.
- **Output size** via `len(pdf_bytes)`.

## Results

Run on 2026-06-06 against `inkmd 0.3.0` and `weasyprint 68.1` with `markdown 3.10.2`, Python 3.13, on SteamOS x86_64.

Earlier runs measured `inkmd 0.1.0` (2026-05-12) and `inkmd 0.2.0` (2026-06-02) against the same WeasyPrint version. The 0.2 line added reference links, hard breaks, indented code blocks, HTML passthrough, image embedding, task lists, a URL-scheme security model, and bundled color emoji; 0.3 took CommonMark and GFM-extension conformance to 100%. Each adds parser/renderer work or install weight. Speed and memory ratios hold within a small band across these releases; the install-size ratio dropped at 0.2 because it bundles the ~10 MB emoji font (see note below).

### Install footprint

```
inkmd venv:      22.3 MB
weasyprint venv: 74.6 MB
```

A complete `inkmd` install is 22.3 MB total venv. A complete `weasyprint + markdown` install is 74.6 MB, *plus* 350-550 MB of system packages (Pango, Cairo, GObject) that pip can't install and that break on Alpine and Windows. inkmd needs none of those.

The `inkmd` package itself is 11.67 MB, of which the bundled Noto Color Emoji font is 10.18 MB, bundled so emoji render anywhere without a system font. The remaining ~1.5 MB is the code plus ~4,700 lines of generated AFM kerning data. If you don't need emoji, the font-less `inkmd.pyz` zipapp is ~170 KB. The rest of the venv is Python's `pip` and base files.

### Cold-start render

This is what you feel from a CLI invocation or a serverless cold start. Each tool runs as a subprocess with markdown on stdin, PDF on stdout. Time includes Python startup and module import.

```
Small (~1 page, ~1 KB markdown -> ~10 KB PDF):
  inkmd:      median 138 ms
  weasyprint: median 731 ms
  ratio: WeasyPrint takes 5.3x longer

Medium (~11 pages, ~15 KB markdown -> ~150 KB PDF):
  inkmd:      median 201 ms
  weasyprint: median 1.40 s
  ratio: WeasyPrint takes 7.0x longer
```

The ratio grows with document size because WeasyPrint's per-page render cost is higher, while inkmd's added work per page is mostly text wrapping and font measurement (both well-cached).

### Memory

Peak resident-set size during a single subprocess render.

```
Small (~1 page):
  inkmd:      18 MB
  weasyprint: 65 MB

Medium (~11 pages):
  inkmd:      20 MB
  weasyprint: 122 MB
```

inkmd's memory is largely flat in document size because the kerning tables are the dominant chunk (~4.5 MB of Python objects after import). WeasyPrint scales upward with document content because it materialises a full DOM-style render tree.

This is the metric most likely to matter for AWS Lambda. inkmd fits comfortably in Lambda's smallest memory profile (128 MB); WeasyPrint needs the 256 MB tier minimum, more for larger documents.

### Output size crossover

```
Small  (~1 page, ~10 KB PDF):   inkmd 10.4 KB, weasyprint 17.1 KB  (inkmd 1.6x smaller)
Medium (~11 pages, ~120 KB PDF): inkmd 150.6 KB, weasyprint 121.8 KB (WeasyPrint 1.24x smaller)
```

WeasyPrint compresses its content streams (flate/zlib), which is a fixed-cost saving that scales with PDF body content. inkmd does not compress streams yet; this is queued for a later patch and is the obvious next perf win.

For documents under ~3 pages, the per-document overhead WeasyPrint pays for its renderer dominates and inkmd's PDFs are smaller. For longer documents, WeasyPrint's compression wins. Both produce valid PDF 1.4 output.

## What this means

A reasonable reading of the data:

- **inkmd is the right tool when** install footprint, cold-start latency, or memory matters. CI artefacts, serverless renderers, embedded systems, locked-down runners, anywhere a 200 MB browser or 74 MB Python venv is not acceptable.
- **WeasyPrint is the right tool when** you need CJK or other scripts the bundled font does not cover, complex-script shaping, CSS-style control over layout, page chrome, or any of the features inkmd doesn't have. (inkmd does render Cyrillic, Greek, and Latin-Extended through an embedded font.) WeasyPrint also produces slightly smaller PDFs for longer documents.

Neither tool is strictly better. They sit at different points on the speed/footprint vs feature-richness trade-off.

## Reproducing

```sh
git clone https://github.com/eagredev/inkmd.git
cd inkmd
python scripts/bench.py --output table
```

First run creates venvs under `bench-venvs/` and installs the comparison tools. Takes around 30 seconds on a reasonable connection. Subsequent runs use the cached venvs.

The script benchmarks both example documents in the repo. Modify `scripts/bench.py` if you want to test against your own markdown.
