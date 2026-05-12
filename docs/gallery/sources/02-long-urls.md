# Long URLs

Real-world URLs from Google search, S3 signed URLs, and JWT auth flows routinely run into the hundreds of characters. The interesting question is how the renderer handles a URL that is longer than the available line width — does it break the URL across a line, hyphenate it, run past the right margin, or wrap cleanly?

## Sentence-length URLs

Visit <https://en.wikipedia.org/wiki/Lorem_ipsum> for background reading.

Compare with <https://en.wikipedia.org/wiki/An_Essay_Concerning_Human_Understanding> which has a noticeably longer slug.

## Paragraph-length URLs

A 200-character URL: <https://example.com/api/v2/resources/very-long-endpoint-name-that-goes-on-and-on-and-on-and-eventually-includes-some-query-parameters?foo=bar&baz=qux&token=abc123&page=1&per_page=100&include=related&extra=padding-here-for-length>

A 500-character URL: <https://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.example.com/path/to/some/resource/that/is/nested/quite/deep/in/an/api?param=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb&other=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc>

## Bare URL forms

Bare URLs work too: https://www.commonmark.org/help/ — and these may render the same as the angle-bracketed form, depending on whether autolinks are enabled.

A URL with parentheses and percent escapes inside the path: https://en.wikipedia.org/wiki/Markdown_(markup_language) — and a query-string version with percent-encoded spaces: https://example.com/search?q=lorem%20ipsum%20dolor

## URL preceded by a parenthesis

Like in academic citations: (see <https://example.com/long-paper-name>).

## URL inside emphasis

Find more at *https://example.com/highlighted-link* in italic.

And **<https://example.com/bold-autolink>** in bold.
