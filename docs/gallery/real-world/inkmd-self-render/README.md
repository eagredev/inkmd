# inkmd README rendered by inkmd

The repository's own README, compiled by the tool it describes.

- Source: `README.md` at the root of this repository
- Licence: MIT (same as the rest of inkmd)
- Rendered: 23,000 bytes of markdown to 14 pages of PDF
- Rendered from the repository root (as `inkmd README.md` would be), so the
  README's relative image paths (the hero) resolve and embed.

## What this demonstrates

The dogfooding exhibit. This is the document a visitor reads in HTML
form on GitHub, now in PDF form via the tool it documents. Headings,
fenced code blocks, GFM tables, mixed-content prose, inline links,
the long feature matrix, and the **color emoji** in the "What you
get" section, which render here as the same color glyphs GitHub
shows: the README demonstrates the feature by containing it.

## What renders well

Tables in the "Supported markdown" section render with header
tinting, grid borders, and the column-alignment hints from the
pipe-table syntax. The "What inkmd doesn't do yet" table is a
three-column layout that flows correctly. Section headings and the
collapsible `<details>` callout near the bottom both render as their
content (CommonMark does not specify a folded representation for
`<details>`; inkmd renders the heading and the body inline, which is
the only sensible thing it can do in PDF output).

## The hero, including the centred `<p align><img>` pattern

The README's hero is `<p align="center"><img src="docs/images/hero-sample.png" width="640"></p>`,
an HTML image inside a centring paragraph, followed by an `<em>`
caption. inkmd promotes the HTML `<img>` tag into the same image
pipeline markdown `![alt](path)` uses, honours the `width` attribute as
a display-width hint (capped to the text column) and the wrapping
`align="center"`, and recognises the image-plus-caption "figure" shape so
the caption renders as text beneath the embedded image. The hero appears,
centred, with its caption. The document renders itself in full.

This used to be the one gap: the `<img>` was dropped as raw HTML, leaving
the README's hero missing in PDF. It now round-trips.

## What still differs from GitHub

The image and its caption render, but the caption is left-aligned
beneath the centred image rather than centred itself (inkmd has no
centred-text-block primitive yet). Remote and SVG images elsewhere fall
back to their alt text, since inkmd embeds raster PNG/JPEG, not SVG.

## Why it's in the gallery

This is inkmd rendering a document the reader is, by definition,
currently looking at in a different rendering. It also surfaces the
current limitations: SVG and remote images fall back to alt text, and
the hero caption renders left-aligned rather than centred.
