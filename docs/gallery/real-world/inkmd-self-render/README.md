# inkmd README rendered by inkmd

The repository's own README, compiled by the tool it describes.

- Source: `README.md` at the root of this repository
- Licence: MIT (same as the rest of inkmd)
- Rendered: 15,950 bytes of markdown to 9 pages of PDF, in 83 ms

## What this demonstrates

The dogfooding exhibit. This is the document a visitor reads in HTML
form on GitHub, now in PDF form via the tool it documents. Headings,
fenced code blocks, GFM tables, mixed-content prose, inline links,
the long feature matrix.

## What renders well

Tables in the "Supported markdown" section render with header
tinting, grid borders, and the column-alignment hints from the
pipe-table syntax. The "What inkmd doesn't do yet" table is a
three-column layout that flows correctly. Section headings and the
collapsible `<details>` callout near the bottom both render as their
content (CommonMark does not specify a folded representation for
`<details>`; inkmd renders the heading and the body inline, which is
the only sensible thing it can do in PDF output).

## What does not render

The hero image at the top of the README is missing. The README
embeds it as `<p align="center"><img src="docs/images/hero-sample.png"></p>`,
which uses inline HTML markup for an image and for centering. inkmd
v0.2's curated inline HTML allow-list does not include `<img>` (only
inline decoration tags such as `<sub>`, `<sup>`, `<mark>`, `<kbd>`).
The image reference is therefore dropped along with the surrounding
HTML, leaving the rest of the README intact but without its hero.

Block-level HTML support, including `<img>` outside markdown image
syntax and the `align` attribute on paragraphs, is queued for v0.3.
A README that uses the markdown image syntax `![alt](path.png)` for
its hero would render with the image embedded in v0.2 today; the
`<p align><img>` pattern specifically is the gap.

## Why it's in the gallery

The dogfooding exhibit demonstrates inkmd on a document the reader
is, by definition, currently looking at in a different rendering.
It also surfaces honest limitations: the missing hero shows where
v0.2 stops and v0.3 starts.
