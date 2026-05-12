# inkmd security

> This document describes inkmd's threat model, what it does and
> does not execute, known issues, and the responsibilities of
> callers who feed it untrusted input. Current as of v0.1.0.

## Summary

inkmd is a pure-Python markdown parser plus PDF byte emitter. It
performs no network I/O, no subprocess execution, no `eval`, no
template expansion, no shell-out. The library function
`inkmd.compile(md_text)` takes a string and returns bytes; that
is the entire contract.

The current security-relevant findings:

1. **URL schemes are filtered by default** (v0.2 change, on by
   default). Only `http:`, `https:`, `mailto:`, `tel:`, `ftp:`, and
   `xmpp:` schemes produce clickable PDF link annotations. Anything
   else (javascript:, data:, vbscript:, file:, custom app schemes)
   renders as plain text with the link annotation dropped. Opt out
   with `safe=False` or `--allow-unsafe-urls` for trusted-content
   use cases. v0.1 shipped without this filter; v0.1 users should
   pre-sanitise untrusted markdown before calling `compile()`.
2. **HTML is escaped, not executed.** Raw HTML in markdown source
   is rendered as escaped text in the PDF, not interpreted. There
   is no HTML executor anywhere in inkmd. v0.2 adds a curated
   safe-subset HTML passthrough (see `docs/design/html-passthrough.md`)
   with a fixed allow-list of tags that have defined, statically-
   resolved PDF rendering — no script interpretation, no CSS, no
   resource fetching, no JavaScript form fields.

The known *non-issues* — things people might expect to be problems
that are not:

- inkmd does not fetch any URLs at parse or render time.
- inkmd does not load fonts from the system. All AFM metric data
  is embedded in the package; rendering uses the 14 base fonts the
  PDF reader provides.
- inkmd does not execute Python code from markdown input.
- inkmd does not write to any file path the caller did not request.

## What the library does

The public API is two functions:

```python
inkmd.compile(md_text: str, **opts) -> bytes
inkmd.render_file(in_path, out_path, **opts) -> None
```

The first reads only the `md_text` argument; it produces a byte
string and returns. It performs no I/O, no network, no subprocess.

The second reads the file at `in_path` (UTF-8 strict) and writes
to `out_path`. These are the only paths the function touches. It
does not honour markdown-embedded references to local files;
images and link references would only be fetched if a *future*
version implemented that feature (it does not in v0.1).

## Threat model: who's adversarial, what they can do

inkmd has two plausible threat scenarios:

**Scenario A: trusted content, trusted operator.** A developer
renders their own README to PDF. The markdown source and the
operator's intent are aligned. No adversary. This is the default
mode and has no security implications beyond ordinary
file-system access.

**Scenario B: untrusted content, trusted operator.** A server or
agent compiles markdown supplied by an external party (user input,
LLM output, fetched documents). The operator wants a PDF; the
content author may be adversarial. This is the interesting case.

In Scenario B, what can an adversarial author do?

- Embed a `javascript:` or `data:` URL in a link. Output PDF
  carries the URL. A reader that honours it executes attacker
  code. **This is the v0.1.0 known issue.**
- Embed a link to an attacker-controlled URL with social
  engineering text. The PDF link is real; the reader will follow
  it. This is the same surface any markdown renderer presents and
  is the *intended* behaviour of a renderer.
- Embed pathologically large content (deeply nested lists, huge
  tables, very long paragraphs). The renderer will spend
  proportional time and memory. We benchmark this below.
- Supply invalid UTF-8 via `render_file`. The file read fails
  with `UnicodeDecodeError`; nothing else happens.
- Supply input containing null bytes, BOM, CRLF, control
  characters. We pass them through to the PDF text content. Most
  PDF readers handle them silently; we do not strip them.

**Scenario C: untrusted operator.** Not a scenario we defend
against. If the operator can call `inkmd.compile()` with arbitrary
arguments, they can already write arbitrary bytes to any path
their process can write to (via the PDF stdin path) — the file
system permissions are the operator's perimeter, not ours.

## Resource exhaustion

Pathological inputs measured on a Steam Deck (AMD Zen2 4-core,
modest clock). Numbers are from
`tests/conformance/resource_probe.py`; re-run to refresh.

| Input | Time | Output size |
|-------|-----:|------------:|
| 1000 nested blockquotes | 72 ms | 25 KB |
| 10000 nested blockquotes | 3.1 s | 245 KB |
| 200 nested lists | 76 ms | 16 KB |
| 5000-row table | 268 ms | 461 KB |
| 200-column table | 9 ms | 19 KB |
| Link with 10000-char URL | 2 ms | 12 KB |
| 5000 leading + 5000 trailing emphasis delimiters | 14 ms | 2 KB |
| (`*a`) repeated 1000 times | 31 ms | 43 KB |

The parser is iterative on the container stack; there is no known
input in v0.1.0 that triggers a `RecursionError` with the default
`sys.setrecursionlimit`. The 10000-blockquote case shows roughly
O(*N*²) scaling. Profiling (2026-05-13, post-Phase-2) localised
the cost to the renderer: each level of `_render_blockquote`
copies the current left-rule offset vector to add its own rule
position. For *N* levels of nesting this is `N + (N-1) + ... + 1 = N²/2`
copies, matching the observed time slope.

In practice this only matters for adversarial inputs: real
documents nest blockquotes a handful of levels at most, so the
per-block cost stays a small constant. We do not "fix" this
because doing so would require restructuring left-rule positions
from "resolved per block at render time" to "composed at PDF-
emission time", a refactor with no benefit to non-pathological
input. The 3-second wall-clock at 10000 deep is well within the
"bounded behaviour on hostile input" envelope this document
describes.

The headline shape across realistic inputs: time is roughly linear
in input size, output size is at most ~5× input size for content-
heavy markdown. If you find an input that takes
disproportionate time or memory, please file an issue at
<https://github.com/eagredev/inkmd/issues>.

If you're calling `inkmd.compile()` on input you do not control,
the prudent operational pattern is the same as for any text-
processing pipeline: bound input length, set a wall-clock timeout
on the call, and limit memory at the OS level (cgroups, ulimits).

## URL handling

When the parser sees `[text](url)`, it places the URL into the
output PDF as a `/URI` annotation, with PDF-syntax escaping
applied (parentheses and backslashes get escaped, the rest passes
through).

**v0.2 added an opt-out URL-scheme filter, on by default.** Only
schemes on the allow-list produce clickable link annotations:

| Scheme | Status |
|--------|--------|
| `http:`, `https:` | Allowed |
| `mailto:` | Allowed (used by GFM email autolinks) |
| `tel:` | Allowed |
| `ftp:` | Allowed |
| `xmpp:` | Allowed |
| `javascript:` | **Filtered** — link text survives, annotation dropped |
| `data:` | **Filtered** |
| `vbscript:` | **Filtered** |
| `file:` | **Filtered** |
| Anything else (custom app schemes, unknown URIs) | **Filtered** |

Relative URLs and fragment-only URLs (no scheme) pass through
unchanged — they cannot navigate out of the document.

**v0.1.0 shipped without this filter** — `javascript:alert(1)` and
similar schemes produced clickable annotations. The historical
behaviour can be restored via `safe=False` on `compile()` /
`render_file()`, or `--allow-unsafe-urls` on the CLI. The opt-out
exists for use cases where the markdown source is trusted
absolutely (a developer rendering their own README, a CI pipeline
compiling content from a vetted repository).

**For untrusted input, leave the default in place.** Filtered
links render as plain text with no visual indicator that filtering
occurred. We deliberately do not advertise "a suspicious URL was
here" in the rendered output — that would leak source information
to anyone viewing the PDF.

## Output handling

The PDF bytes produced by inkmd contain *only* content derived
from the markdown source plus inkmd's own scaffolding (catalog
dictionary, page tree, font references, fixed kerning tables).

inkmd's PDF emitter:

- Does not embed any JavaScript actions, form actions, OpenAction
  triggers, or AcroForm fields.
- Does not embed any embedded files (`/EmbeddedFile`), file
  attachments, or alternate file references.
- Does not embed any external streams. Every byte is generated
  inline.
- Does not embed font outlines or any binary glyph data. Fonts
  are referenced by name only; the reader provides the outlines.

The only "active content" the PDF can contain is `/URI` link
annotations, which are subject to the limitation above.

## Determinism as a security property

Same markdown input always produces same PDF bytes. No clocks, no
random IDs, no platform-dependent iteration order. This is
documented in the README as a feature; it is also a security
property — it lets callers:

- Hash inputs and outputs and store the relationship as a trust
  binding (e.g. signed PDFs in audit pipelines).
- Diff two PDF outputs and conclude that any difference reflects
  a real difference in the markdown, not a build-environment
  difference.
- Detect tampering: if the PDF doesn't match the recompiled hash,
  something changed.

## What inkmd does not promise

- **PDF/A or PDF/UA compliance.** v0.1 PDFs are valid PDF 1.4 but
  are not certified against archival or accessibility specs.
- **Resistance to file-system attacks at the CLI level.** The CLI
  reads and writes whatever paths the caller gives it. Symlink
  attacks, race conditions on output paths, and similar are the
  caller's responsibility.
- **Protection against adversarial PDF readers.** If a reader
  honours a `javascript:` URL or otherwise behaves unsafely on a
  conforming PDF, that's the reader's bug, not inkmd's. inkmd's
  job is to produce well-formed PDFs that contain only the
  content the markdown specified.
- **Resistance to crafted PDFs as input.** inkmd produces PDFs; it
  does not consume them.

## Reporting issues

If you find a security issue:

- File a public issue at <https://github.com/eagredev/inkmd/issues>
  if the issue is one the world can already discover by running
  the conformance suite or by reading this document.
- Email the maintainer directly for issues not yet public. The
  email is on the maintainer's GitHub profile.

There is no bug bounty programme. inkmd is a small, single-
maintainer open-source tool. We treat security issues seriously
but cannot make response-time guarantees.

## Reproducing the findings in this document

Every finding here is reproducible from the v0.1.0 source. The
resource-exhaustion measurements are in
`tests/conformance/resource_probe.py` (added in the Phase 1
hardening pass); the URL-handling demo is a single-line `compile()`
call. There are no claims in this document that you cannot verify
yourself in under a minute.
