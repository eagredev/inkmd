# Design principle: utter consistency over local taste

**Status:** the governing design principle for inkmd, settled 2026-05-13.
**Scope:** why inkmd chases CommonMark/GFM conformance instead of making
case-by-case "this looks nicer" choices, and how to apply that when the
spec is silent. This is the principle the conformance numbers are a *proxy*
for; it is not the same thing as the numbers.

## The principle

> "We're processing any variety of documents, for any variety of purposes.
> If we made a design choice that makes sense for one use case or document
> type, then we could be negatively impacting a different legitimate use
> case, because we don't actually know what people are going to use it for.
> The idea is consistency. It may not be perfectly optimised, and it may not
> match every specific design quirk that some specific people may prefer, but
> that's by design. Our goal is utter consistency."

For any markdown construct the CommonMark spec gives a clear answer about,
inkmd follows that answer, even when a different choice would look prettier
or be smarter for one particular workflow.

## Why

inkmd is a **general-purpose** tool with no opinion about who is using it.
Its users span CV writers, academic note-takers, README publishers, agents
generating reports, CI pipelines. Contrast a tool that knows its audience:
Python-Markdown can confidently say "we'll never be fully CommonMark
compliant" because it serves Django-style docs sites and *knows* what those
need. inkmd doesn't have that luxury, and shouldn't pretend to.

The consequence is sharp: **a "smart" local choice that benefits one workflow
can silently break another the author can't see.** If inkmd decided, say, to
collapse a particular whitespace pattern because it looked cleaner in a CV, it
would corrupt a document where that whitespace was load-bearing. The tool has
no way to know which workflow it's serving on any given input, so optimising
for one is gambling with the others.

The CommonMark spec is the closest available proxy for **"what most other
tools agree this should mean."** Following it is what makes a document written
in Obsidian, VS Code, or GitHub render the *same* in inkmd. Deviating from it
for taste creates surprise, and surprise, in a format-conversion tool, is the
cardinal sin. This is the same instinct as the broader engineering rule of
not making local choices that look fine in isolation but break consumers
downstream who can't see the choice you made.

## How to apply

- **Where the spec is clear, follow it,** even against a prettier or
  cleverer local alternative. The cost of inconsistency-across-tools is higher
  than the benefit of marginal local cleverness.
- **Where the spec gives latitude or is silent** (e.g. inkmd's PDF-specific
  rendering of `<mark>` highlights, `<kbd>` borders, exact font sizes, table
  grid styling): make a deliberate choice and **document it**. The principle is
  "be *predictable* where the spec is predictable," not "follow the spec for
  things the spec doesn't address."
- **When a conformance-breaking choice is genuinely necessary, document it as
  a deliberate exception, not a quirk.** inkmd's exceptions are about safety,
  not taste: the URL-scheme filter blocks `javascript:` (so a malicious link
  can't ship an executable annotation), and remote image fetch is off by
  default (so an untrusted document can't make the renderer reach the
  network). Both are conscious, documented deviations; see `security.md`.

## The number is evidence, not the claim

The conformance percentage (CommonMark 652/652, GFM-ext 28/28 as of v0.3) is
**evidence for the principle, not the principle itself.** The principle is:

> **Utter consistency: what GitHub showed you is what you get.**

That sentence is the actual promise; the percentage is how progress toward it
is measured. "It renders your document the way every other tool does" describes
the property a reader cares about, where a bare spec-suite number does not.

This also reframes what a *failing* spec test means. A failure is only a real
problem if it changes what a user sees. A failure that produces a slightly
different HTML AST but a byte-identical-looking PDF is a long-tail cleanup, not
a broken promise. (This is why inkmd's release tiers, described in the roadmap,
are defined by user-visible quality, not by hitting a conformance number.)

## The deeper rule this is an instance of

"Utter consistency over taste" is one face of a more general engineering
stance: **don't optimise a shared interface for the consumer you happen to be
looking at.** A markdown-to-PDF renderer's "interface" is the meaning of each
construct; its consumers are every document anyone will ever feed it. The same
stance shows up elsewhere as "don't make a local fix that helps the symptom in
front of you but rots a sibling case you can't see." Predictability for *all*
consumers beats optimisation for the *visible* one.

## Cross-references

- `docs/conformance.md`: the per-section numbers (the proxy).
- `docs/design/emoji-architecture-decision.md`: the emoji fallback covers
  *all* unrepresentable codepoints, an application of this principle.
- `docs/security.md`: the deliberate, documented conformance exceptions.
