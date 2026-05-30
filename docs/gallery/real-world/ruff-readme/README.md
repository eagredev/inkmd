# Ruff README

The README for Ruff, the Python linter and code formatter, rendered
by inkmd.

- Source: <https://github.com/astral-sh/ruff/blob/main/README.md>
- Licence: MIT (the `astral-sh/ruff` repository)
- Rendered: 25,306 bytes of markdown to 11 pages of PDF, in 966 ms
  (with `--allow-remote-images` enabled; remote fetches account for
  most of the time)

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

## What does not render

**Emojis.** The Ruff feature list opens with one emoji per bullet
(rocket, lightning, snake, etc.). inkmd v0.2 uses PDF's 14 standard
base fonts in the WinAnsi single-byte encoding; emoji codepoints
have no byte to spell them with and render as `?` markers. The
feature list therefore reads as `?? 10-100x faster ...`, `? Installable
via pip ...`, and so on. This is the documented v0.2 typography
limitation and lifts in v0.3 with TTF font embedding.

**Shields.io badges.** The README's hero line includes six shields.io
badges (PyPI version, licence, supported Python versions, CI status,
Discord). All are SVG-format images. inkmd v0.2 supports PNG and
JPEG image embedding but not SVG. With `--allow-remote-images`
enabled, the remote fetches succeed but the SVG payloads are not
decoded, and the references fall back to their alt text. The badges
therefore render as the literal alt-text sequence
`Ruff image image image Actions status Discord` near the top.

## Why it's in the gallery

The gallery would be dishonest without an exhibit that hits inkmd's
documented limits. The Ruff README does. The rest of the document
renders well; the emoji-as-`?` markers and the badge alt-text are
the visible cost of inkmd's "no system dependencies, no font files,
no SVG renderer" promise. Trading those two surfaces for a 11 MB
installed footprint and 100 ms cold start is the deal inkmd offers,
and an honest gallery should let the reader see what the deal looks
like in practice.

Both gaps are documented in `README.md` and in `docs/conformance.md`;
both close in later versions (SVG and RGBA PNG in v0.3, TTF font
embedding in v0.3).
