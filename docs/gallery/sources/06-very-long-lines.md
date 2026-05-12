# Very long lines

A markdown paragraph is one logical line per `\n\n` separator, but the physical line can be hundreds or thousands of characters. The renderer's job is to wrap text into the available width using the font's advance widths and kerning data. Long input lines are a stress test for the line-wrapping algorithm — they must produce visually balanced lines, never overflow the right margin, never lose words at break points, and survive interaction with inline formatting.

Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo.

A paragraph with **bold**, *italic*, `code`, and [a link](https://example.com) interleaved at a high density: this **sentence** contains *several* `formatting` tokens [back](https://example.com)-to-back *with* **alternating** types `to` exercise [the](https://example.com) **token-grouping** *logic* `under` [load](https://example.com), each one introducing a font change, an underline annotation, or a background tint.

A paragraph that contains, in the middle of an otherwise normal sentence, one extremely long token like supercalifragilisticexpialidociousantidisestablishmentarianismpneumonoultramicroscopicsilicovolcanoconiosispseudopseudohypoparathyroidismfloccinaucinihilipilificationhippopotomonstrosesquippedaliophobia which exceeds the line width on its own and must either wrap mid-token (visually awkward but correct) or overflow the right margin (a bug).

Multiple very long words in succession: pneumonoultramicroscopicsilicovolcanoconiosis hippopotomonstrosesquippedaliophobia pseudopseudohypoparathyroidism floccinaucinihilipilification antidisestablishmentarianism — the wrapping algorithm has to decide where to break each one.

A paragraph wrapped in **bold** around its entire length: **Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur.**

A paragraph wrapped in `inline code` around its entire length, which means a fixed-width font from start to finish: `Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.`

A paragraph that is one URL: <https://example.com/an-extremely-long-path-segment-that-keeps-going-and-going-and-eventually-includes-some-query-parameters-too?param=value&other=parameter&yet=another&and=one&more=for-good-measure>
