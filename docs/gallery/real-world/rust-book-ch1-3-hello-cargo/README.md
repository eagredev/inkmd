# The Rust Book §1.3: "Hello, Cargo!"

Chapter 1.3 of *The Rust Programming Language*.

- Source: <https://github.com/rust-lang/book/blob/main/src/ch01-03-hello-cargo.md>
- Licence: MIT or Apache-2.0 (the `rust-lang/book` repository, per its
  LICENSE-MIT and LICENSE-APACHE files)
- Rendered: 10,911 bytes of markdown to 5 pages of PDF, in 65 ms

## What this demonstrates

A multi-page technical book chapter: prose, numerous fenced code
blocks (mostly `console` and `toml`), section headings of varied
depth, italic emphasis, internal cross-reference link targets,
inline code. This is the longform-documentation case.

The render is clean. All twenty fenced code blocks render with their
language tags and tinted backgrounds, italic emphasis on terminology
("Rustaceans," "dependencies") is preserved, the prose flows across
page breaks without orphaning, and inline code such as `cargo new`
renders in Courier.

## Why it's in the gallery

Demonstrates inkmd on a longform multi-page document where the
challenge is not any single feature but consistent rendering and
clean page-flow across substantial length.

## What we deliberately avoided

Earlier chapters of *The Rust Book* (notably 3.2 "Data Types") use
mdBook template directives such as `{{#include ...}}` and
`{{#rustdoc_include ...}}` to pull code listings from external files.
inkmd is a markdown compiler, not an mdBook preprocessor, so it
renders these directives as literal strings. We picked a chapter
without those directives so the gallery exhibit is representative
of inkmd rendering markdown, not inkmd failing to be mdBook.
