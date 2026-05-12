# Thematic-break interactions

A thematic break (`---`, `***`, `___`) is a block-level structure that resembles other syntax. The parser must distinguish a setext-heading underline (`---` immediately after a paragraph) from a thematic break (`---` with a blank line above).

## Standard form

A paragraph.

---

Another paragraph.

## Three forms

The CommonMark spec accepts `---`, `***`, and `___` (three or more, optionally spaced).

A paragraph.

***

Star-form rule above.

___

Underscore-form rule above.

------------

Multi-dash form above.

* * *

Spaced dashes above.

## Setext heading vs thematic break

A line of text
---

This should render as a Setext H2 ("A line of text"), NOT as a paragraph followed by a thematic break.

A line of text

---

This (with a blank line) should render as a paragraph followed by a thematic break.

## Thematic break next to a list

- item one
- item two

---

- item three (new list after the break)
- item four

The break should terminate the first list; the items below should be a fresh list, not a continuation.

## Three asterisks in a paragraph

This is a paragraph that contains *** in the middle. That should be six asterisks of emphasis processing, not a thematic break.

## Three dashes immediately after text

End of paragraph one.
---

Strict CommonMark parses this as a setext heading "End of paragraph one." Many tools (and most users' mental models) parse it as a paragraph followed by a thematic break. We follow the spec.

## Thematic break that looks like a YAML front matter

---
title: example
date: 2026-05-12
---

In strict CommonMark (which we follow) this is: (1) thematic break, (2) paragraph "title: example date: 2026-05-12", (3) setext-H2 underline that turns the preceding paragraph into an H2 with text "title: example date: 2026-05-12". YAML front matter is not a CommonMark feature; we do not detect or strip it.

## Thematic break in a blockquote

> Quote content.
>
> ---
>
> More quote content.

The break should render inside the quote.

## Thematic break in a list

- item one

  ---

- item two

The break should render inside the item (as part of item one) or as a list-terminator (a known ambiguity). CommonMark says terminator; we follow.
