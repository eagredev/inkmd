# HTML passthrough — v0.2 scope decision

> Design document, drafted 2026-05-13 during Phase 3 of the pre-HN
> hardening pass. Captures the reasoning behind whether and how
> inkmd v0.2 should accept HTML inside markdown.

## The question

CommonMark 0.31.2 allocates 64 of its 652 spec tests to HTML
behaviour:

- §4.6 **HTML blocks** (44 tests, currently 0/44) — top-level HTML
  fragments like `<div>...</div>`, `<table>`, `<pre>`, `<!--...-->`.
- §6.6 **Raw HTML** (20 tests, currently 7/20) — inline HTML mid-
  paragraph like `<sub>`, `<kbd>`, `<a name="anchor">`, comments,
  CDATA, processing instructions.

GFM 0.29 adds §6.11 **Disallowed Raw HTML** (1 test) which strips
specific dangerous tags from passthrough output.

inkmd v0.1 treats every `<` as a literal character to escape, except
where it opens a CommonMark autolink (`<https://...>`). Raw HTML and
HTML blocks render as visible escaped text.

**The decision**: does v0.2 implement HTML passthrough? And if so,
which subset, with what PDF semantics, under what security model?

## Background: why CommonMark's HTML rule is awkward for PDF

CommonMark passthrough means "preserve the literal characters in the
output HTML". The downstream browser interprets the HTML when it
renders the page. Markdown-to-HTML tools don't have to know what
`<details>` means — they just have to not mangle it.

inkmd's output is PDF, not HTML. There is no downstream renderer
that will later "interpret" the HTML. If a user writes:

```markdown
<details>
<summary>Click to expand</summary>
hidden content
</details>
```

then for inkmd to do anything more useful than ignore the tags, **we
have to decide what `<details>` means in a PDF**. Every supported
tag is a design decision and a renderer-feature commitment, not just
a parser change. This is a *much* bigger constraint than for an
HTML-output tool.

The alternative — "parse the HTML and render only its text content,
dropping the tags entirely" — would technically pass some
passthrough tests (the parser would no longer escape `<` to `&lt;`)
but the result would be functionally useless: `<details><summary>X
</summary>Y</details>` would render as `XY` with no indication of
collapsibility, which is worse than the current behaviour because
users would expect *something* to happen.

## Three options

### Option A — Stay closed (no HTML passthrough)

Reject every `<tag>` as literal text, as today. Document the choice
in the README as a feature, not a bug:

> inkmd is markdown-to-PDF, not HTML-to-PDF. If you need HTML in
> your output, use a tool that produces HTML.

**Pros:**

- Zero security surface from HTML interpretation
- Zero new code, zero new design decisions
- Zero ambiguity about output behaviour
- Conformance numbers stay where they are (0/44 + 7/20)

**Cons:**

- GitHub README convention uses `<details>`, `<sub>`, `<sup>`,
  `<kbd>`, `<br>`, `<a name>` heavily. Rendering a GitHub README
  through inkmd produces visibly escaped `<details>` text where the
  user expected collapsible behaviour. **inkmd's own README** uses
  `<details>` for the font-rendering note and would render that
  literally.
- "We don't do that" is a defensible position but it costs users who
  expected markdown-renderer-of-the-month behaviour.

### Option B — Curated safe subset with PDF semantics

Accept a fixed allow-list of tags with defined PDF rendering.
Everything outside the list is silently dropped (text content
preserved, tags removed). The allow-list:

| Tag | PDF semantics |
|-----|---------------|
| `<br>` / `<br/>` / `<br />` | Hard line break (same as the CommonMark `  \n` form) |
| `<sub>` | Subscript: smaller font, lowered baseline |
| `<sup>` | Superscript: smaller font, raised baseline |
| `<kbd>` | Keyboard key: monospace font with bordered background |
| `<mark>` | Highlight: yellow background tint behind text |
| `<u>` | Underline (we draw an underline rule) |
| `<s>` / `<strike>` | Strikethrough (same as GFM `~~text~~`) |
| `<details>` + `<summary>` | A boxed section: summary always visible as a heading-styled line, body content below in normal flow. PDF can't truly collapse, so we render the contents expanded; the summary is a visual marker for "this is supplementary." |
| `<a name="X">` | Set a PDF named destination for in-document links |
| HTML comments `<!-- ... -->` | Stripped entirely (consistent with the existing "comments are not output" expectation) |

Attributes:

- `href`, `title`, `id`, `name` — preserved for `<a>` only.
- `style`, `class`, `onclick`, anything else — dropped, ignored.

Tags not on the list:

- Stripped: the tag itself is discarded, but enclosed text content
  passes through. So `<span style="color:red">hello</span>` becomes
  just `hello` in the output. This handles 90% of real-world
  README content where users use spans for styling we can't honour.
- Block-level unknown tags: `<table>`, `<iframe>`, `<script>`,
  `<style>`, `<object>`, `<embed>`, `<form>`, `<input>` — silently
  dropped including their content.

**Pros:**

- Covers the realistic GitHub-README use case
- No script execution risk (we never interpret JavaScript, never
  evaluate CSS, never load external resources)
- inkmd's own README would render correctly through itself
- Adds maybe 10-15 conformance tests we can credibly claim
- Differentiates inkmd from WeasyPrint/Chrome on a security axis:
  "we accept a defined safe subset with defined PDF semantics; the
  others accept arbitrary HTML with browser-engine attack surface"

**Cons:**

- Real new code in three layers (block parser detects HTML opening
  tags, inline tokeniser recognises inline tags, render layer
  applies PDF semantics for each supported tag)
- Each supported tag is a renderer-feature commitment that needs
  test coverage
- "Stripped unknown tags drop silently" surprises users when their
  `<table>` disappears. Mitigation: opt-in `--html-strict` mode that
  errors on unknown tags
- Adds a flag and a config decision to the public API surface

### Option C — Permissive parse, drop everything

Recognise HTML constructs structurally so we don't escape them in
the output, but render only the text content (no tag semantics).

**Pros:**

- Lifts the conformance tests where the spec expected literal
  passthrough (~30 tests).
- No security model needed; we never interpret anything.

**Cons:**

- Users see their tags vanish from their rendered output. `<details>`
  loses its summary visually. `<sub>2</sub>` loses the subscript.
- Worse than Option A in real terms because we look like we
  *tried* to support HTML and silently failed.
- Conformance gain is hollow: we pass the byte-comparison tests but
  the rendered PDF is functionally degraded vs. the source intent.

## Recommendation: Option B

The cost of A is real (the GitHub-README use case is the entire
point of half our user base), and C is a worst-of-both choice that
costs visible quality for hollow conformance.

B is the right architectural choice for the long term:

- It keeps the security story clean: inkmd has no HTML interpreter,
  no script evaluator, no resource fetcher. The allow-list is a
  static set of tags with statically-defined PDF rendering.
- It maximises the surface where users get what they expected from
  GitHub-flavoured markdown.
- It tells a clear story on Hacker News: "we accept a curated safe
  subset; here is the list; here is the rationale." That's
  defensible against the "but my edge case" objections.
- The conformance gain is bounded but real: maybe 15-20 tests as a
  side effect, plus the qualitative win of "rendering a real-world
  README through inkmd produces the same visual semantics."

## Scope for v0.2

The v0.2 work to ship Option B:

**Parser layer:**

- Block-level: recognise the seven CommonMark HTML-block types in
  §4.6 (the parser needs to know "this is HTML so don't tokenise
  the contents as markdown"). For the *closed* tag set we accept,
  preserve the AST; for unknown tags, decide at parse time whether
  to keep the contents or drop them based on the structural type.
- Inline-level: recognise the HTML tag forms (open tag, close tag,
  comment, processing instruction, declaration, CDATA section) per
  CommonMark §6.6. For our allow-list tags, build an AST node with
  rendering hints; for unrecognised tags, drop the tag-syntax but
  keep the enclosed text.

**AST:**

- New inline node `HtmlInline(tag: str, content: tuple[Inline, ...],
  attrs: dict[str, str])` — used only for our allow-listed tags.
- New block node `HtmlBlock(kind: str, content: str)` — placeholder
  for the v0.2 details/summary block-level form.

**Render + PDF:**

- Sub/sup: smaller font + offset baseline. Run through the existing
  layout engine with adjusted size + y-offset metadata.
- Kbd: monospace + a thin grey border rectangle. New layout
  primitive (similar to code-block background but tighter).
- Mark: yellow background tint per text run.
- Br: hard line break — coordinate with the separate v0.2 hard-line-
  break work, share the same internal primitive.
- Details/summary: box with the summary rendered as a small heading
  followed by the content in normal flow. No collapsibility (PDF
  doesn't have it without JavaScript form fields, which we don't
  emit).
- A-name: emit a PDF named destination dictionary entry pointing at
  the y-coordinate of the anchor's containing block.

**CLI / API:**

- Default: HTML allow-list active.
- `--html-strict`: error on any HTML construct outside the allow-list
  rather than silently dropping it. Useful for content authors who
  want a guarantee that the renderer sees everything they wrote.
- `--no-html`: revert to v0.1 behaviour (every `<` is literal text).
  Useful for environments where the content is fully trusted but
  HTML-passthrough is undesired.

**Security model update:**

- `docs/security.md` gets a new section enumerating the allow-list,
  the dropped-or-passed disposition for each known tag, and the
  explicit non-interpretation of style/script/onclick attributes.
- The threat model already covers Scenario B (untrusted content);
  Option B fits cleanly because there is no new untrusted-execution
  surface — every supported tag has a fixed, statically-defined PDF
  rendering.

## What this means for the v0.2 plan

HTML passthrough joins the v0.2 feature ordering as a sibling of
images and reference links. Rough sizing:

- **Reference links**: ~600 LoC, ~25 conformance tests
- **Images**: ~1000 LoC (PNG/JPEG decode + embed + layout), ~22
  conformance tests
- **HTML passthrough (Option B)**: ~1500 LoC across parser, render,
  PDF emitter, ~15 conformance tests + qualitative GitHub-README
  parity
- **Hard line breaks**: ~200 LoC, ~10 tests (shares the `<br>` PDF
  primitive with HTML passthrough, worth doing together)
- **Task lists**: ~100 LoC, 2 tests + qualitative GFM tell
- **Indented code blocks**: ~400 LoC parser refactor, ~10 tests
- **URL scheme filter (already designed)**: ~50 LoC, security
  improvement (no conformance impact)

Total v0.2 estimate: ~4000 LoC of focused work, ~85 conformance
tests, plus the security and qualitative improvements. At current
pace that is ~3-5 focused sessions to implement and test.

## Open questions

These need user input before implementation starts:

1. **Should `<details>` actually render expanded in the PDF, or
   should we keep it collapsed with a "[+] expand" indicator like
   GitHub does in print view?** Recommendation: expanded by default;
   PDF cannot truly collapse without JavaScript form fields; a `[+]`
   indicator is misleading.

2. **Should we accept GitHub-style `<picture>` and `<source>` for
   responsive images?** Recommendation: no for v0.2; if we
   implement images they go through the markdown `![](url)` syntax,
   not via passthrough HTML. Keep the allow-list small.

3. **Should `<a href>` HTML links be treated the same as markdown
   `[text](url)` links?** Recommendation: yes, treat them as
   equivalent and route through the same Link AST node — saves a
   render-side branch and means we can apply the same URL-scheme
   filter (task 36) to both.

4. **Should HTML comments be visible or stripped?** Recommendation:
   stripped. They're authoring artefacts; users do not expect them
   in printed output. Counter-argument: stripping makes round-
   tripping impossible. We do not aim to round-trip; markdown is
   the source of truth.
