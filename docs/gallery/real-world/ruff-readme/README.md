# Ruff README

The README for Ruff, the Python linter and code formatter, rendered
by inkmd.

- Source: <https://github.com/astral-sh/ruff/blob/main/README.md>
- Licence: MIT (the `astral-sh/ruff` repository)
- Rendered: 25,306 bytes of markdown to 11 pages of PDF
  (with `--allow-remote-images` enabled; remote fetches account for
  most of the wall time)

## What this demonstrates

A widely-recognised open-source-project README: hero badges, headline
positioning, a feature bullet list, sections for installation,
configuration, comparisons with other tools, and a long "Who's
using Ruff?" list. The kind of document a developer encounters
several times a week on GitHub.

## What renders well

Headings, prose, code blocks, inline links, ordered and unordered
lists, and the project's section structure all render cleanly across
the 11 pages. Code blocks for installation commands, configuration
examples, and CLI invocations carry their fenced language tags and
tinted backgrounds. The "Who's using Ruff?" list renders as a long
bullet list with each project hyperlinked.

The feature list opens with one emoji per bullet (lightning, snake,
hammer-and-wrench, and so on). These render as full-color glyphs,
embedded from the bundled Noto Color Emoji font, so the bullets read
the same way they do on GitHub rather than as fallback markers.

## What does not render

**Shields.io badges.** The README's hero line includes six shields.io
badges (PyPI version, licence, supported Python versions, CI status,
Discord). All are SVG-format images. inkmd embeds PNG and JPEG but
not SVG. With `--allow-remote-images` enabled, the remote fetches
succeed but the SVG payloads are not decoded, and the references fall
back to their alt text. The badges therefore render as the literal
alt-text sequence `Ruff image image image Actions status Discord`
near the top.

## Why it's in the gallery

The gallery would be dishonest without an exhibit that hits inkmd's
documented limits. The Ruff README does: the SVG badges fall back to
alt text, which is the visible cost of inkmd's "no system
dependencies, no SVG renderer" promise. The rest of the document,
including the color emoji and every code block, renders cleanly.
Trading SVG support for a 22.3 MB installed footprint and a cold
start measured in milliseconds is the deal inkmd offers, and an
honest gallery should let the reader see what the deal looks like in
practice.

The SVG gap is documented in `README.md` and in `docs/conformance.md`.
