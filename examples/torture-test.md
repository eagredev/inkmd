# inkmd Torture Test

A deliberate stress test of every feature. If something here renders wrong, it's a bug to triage. The document spans multiple pages and exercises corner cases that real-world documents rarely hit but should still survive.

This opening paragraph contains a representative sample of inline formatting: **bold**, *italic*, ***bold-italic***, `inline code`, a [link](https://example.com), an <https://example.com> autolink, an email <dylan@example.com>, an em-dash —, en-dash –, curly "quotes" and 'apostrophes', ellipsis …, and a backslash-escaped \*literal asterisk\* plus \_literal underscore\_.

---

## Heading hierarchy

The six ATX heading levels follow. Each should be visibly smaller than the previous, all bold.

### H3 — three hashes

#### H4 — four hashes

##### H5 — five hashes

###### H6 — six hashes (smallest)

A Setext H1 follows:

Setext H1 alternate form
========================

A Setext H2 follows:

Setext H2 alternate form
------------------------

A heading with **inline emphasis** and *italic* and `code` and [a link](https://example.com) — all should stay at heading size.

### Heading with ## interior hashes that should NOT be stripped

### Trailing closing hashes should be stripped ###

## CommonMark inline edge cases

This section abuses the inline parser. Each line is a separate paragraph to keep them visually distinct.

Plain **bold**. Plain *italic*. Mixed **bold with *italic inside* outer bold**. Triple ***both at once***. Nested **bold *italic **deeper bold** italic* outer**.

Underscores: _italic_ and __bold__ and ___both___. Mixed: _italic with **bold** inside_ and **bold with _italic_ inside**.

Intraword underscores stay literal: snake_case_name, my_python_var, hello_world_function. Intraword asterisks DO emphasise: intra*word*emph and a*b*c.

The rule of 3: **foo**bar**baz** should make the outer pair emphasis. ***strong and italic*** should produce both. *foo**bar** should NOT make bold (length sum = 3).

Backslash escapes: \*literal\*, \_literal\_, \`literal\`, \[not a link\], \\actual backslash, \!not bang.

Code spans: `simple`, `with **literal asterisks**`, `with \*escaped\* and \\backslash`. Spaces in code: `  leading and trailing  ` preserved? Empty code span: `` `` (or with content? `nope`).

Unmatched delimiters: *not closed should be literal asterisk, **not closed either, _underscore unclosed.

A paragraph with a long word: supercalifragilisticexpialidociousantidisestablishmentarianismpneumonoultramicroscopicsilicovolcanoconiosis that should overflow or wrap or stay-as-one-token.

## GFM strikethrough (added 0.0.12)

Basic: ~~struck~~ in the middle of a sentence.

Multi-word: a phrase like ~~the old approach~~ should produce one continuous horizontal bar across all the struck words, not one bar per word.

Two separate strikes on one line: ~~first~~ then unstruck then ~~second~~ should produce two distinct bars with the unstruck text in between.

Nesting both ways: ~~**struck-and-bold**~~ and **~~bold-and-struck~~** and ~~*struck-italic*~~ and *~~italic-struck~~* — the bar should cross all of them while the font weight/slant still applies.

Strike on a link: [~~deprecated page~~](https://example.com) — should still be clickable, blue, underlined, AND struck.

Single tildes stay literal: this 1~2 isn't strikethrough, neither is a~tilde~b, and three or more ~~~triples~~~ inline are also literal.

A long ~~struck phrase that runs across what should be a forced line break in a sufficiently narrow column so that we can verify the strike rectangle re-anchors at the start of the wrapped second line correctly~~ end.

## Lists, deeply nested

A flat unordered list:

- Apple
- Banana
- Cherry

A flat ordered list with arbitrary start:

5. Five
6. Six
7. Seven

Mixed marker characters (each starts a new list):

- dash item
* asterisk item
+ plus item

Nested four levels deep:

- Level 1, item A
    - Level 2, item A.1
        - Level 3, item A.1.1
            - Level 4, item A.1.1.1
            - Level 4, item A.1.1.2
        - Level 3, item A.1.2
    - Level 2, item A.2
- Level 1, item B

Mixed ordered and unordered nesting:

1. Outer ordered item one
    - Inner bullet a
    - Inner bullet b
        1. Deeper ordered i
        2. Deeper ordered ii
2. Outer ordered item two

A tight list followed by a loose list:

- tight 1
- tight 2
- tight 3

(blank line)

- loose 1

- loose 2

- loose 3

A list with **bold**, *italic*, `code`, and [links](https://example.com) inside items:

- **Bold** item
- *Italic* item
- `Code` item
- A [link inside](https://example.com) item
- Mixed **bold with *italic* and `code` and [a link](https://example.com)** all in one item

Items with very long content that wraps:

- This is a much longer item that should wrap onto a second line when it exceeds the available column width, demonstrating hanging-indent behavior where the continuation aligns with the body column rather than the marker column.
- Another long item: lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua, just to be sure.

Empty list items:

-
- after empty
-

## Blockquotes, including nesting and embedded content

A flat blockquote:

> A simple single-paragraph blockquote.
> Wrapped across multiple source lines but rendered as one paragraph.

A multi-paragraph blockquote:

> First paragraph of the quote.
>
> Second paragraph after a blank quote line. The vertical rule should continue through both paragraphs.

A nested blockquote:

> Outer quote.
>
> > Inner quote, two levels deep.
> >
> > > Three levels deep — three vertical rules side by side.

A blockquote containing a heading:

> ## A heading inside a blockquote
>
> Body text after the heading inside the quote.

A blockquote containing a list:

> Items in a quote:
>
> - First quoted item
> - Second quoted item
>     - Nested inside a quoted list
> - Third quoted item

A blockquote containing a code block:

> Here is some quoted code:
>
> ```python
> def quoted_code():
>     return "this is inside a blockquote"
> ```
>
> And body text after it.

A blockquote containing a link:

> Visit [the homepage](https://example.com) for more information.

## Fenced code blocks

A plain code block with no language:

```
plain text
preserved   spaces
    indented four
\ttab character (literal backslash-t since we expanded tabs)
   leading three spaces
no leading spaces at all
```

A Python code block:

```python
def factorial(n: int) -> int:
    """Compute n! recursively."""
    if n <= 1:
        return 1
    return n * factorial(n - 1)

# Usage
for i in range(10):
    print(f"{i}! = {factorial(i)}")
```

A code block with tildes:

~~~rust
fn main() {
    println!("Hello from a tilde-fenced block!");
}
~~~

A code block with backticks inside (4-backtick fence):

````
You can write ``` inside if the outer fence is longer.
And `single backticks` too.
````

A code block with markdown-like content that should NOT be interpreted:

```
**not bold**
*not italic*
`not code`
[not a link](nowhere)
# not a heading
- not a list item
> not a blockquote
| not | a | table |
```

A very long code line — should now soft-wrap at column boundary (fixed 0.0.11.2):

```
This is a deliberately very long single line of code that will exceed the available column width and may visually overflow the background tint rectangle, which is acceptable behavior for preserved-whitespace code blocks.
```

## Tables with everything

A simple three-column table:

| Header 1 | Header 2 | Header 3 |
| -------- | -------- | -------- |
| cell 1.1 | cell 1.2 | cell 1.3 |
| cell 2.1 | cell 2.2 | cell 2.3 |

A table with all three alignments:

| Left   | Center | Right |
| :----- | :----: | ----: |
| a      | b      | c     |
| longer | x      | 99    |
| short  | longer center | 3.14 |

A table with inline formatting in cells:

| Style | Example | Result |
| --- | --- | --- |
| Bold | `**hi**` | **hi** |
| Italic | `*hi*` | *hi* |
| Code | `` `x` `` | `x` |
| Link | `[ex](url)` | [example](https://example.com) |
| All | mixed | **bold *and italic* and `code` and [link](https://example.com)** |

A table where cells contain text that must wrap (column widths shrink):

| Topic | Description |
| ----- | ----------- |
| First | A reasonably long description that should wrap inside its cell when the table is narrower than the natural content width would require. |
| Second | Another lengthy description containing **bold** and *italic* and [a link](https://example.com) mixed with regular text to test inline formatting inside wrapped cell content. |
| Third | Short. |

A table with no leading/trailing pipes:

A | B | C
:--- | :---: | ---:
1 | 2 | 3
left-leaning | centered-x | right-99

A table with escaped pipes in cells:

| Operator | Meaning |
| --- | --- |
| `\|` | Logical OR |
| `&&` | Logical AND |
| a \| b | The pipe character itself |

A table that's just header + delimiter, no body rows:

| Empty Body | Still Valid |
| ---------- | ----------- |

## Links — every variation

Inline links: [click here](https://example.com), [with title](https://example.com "Tooltip text"), [angle-form](<https://example.com>).

Autolinks: <https://example.com>, <http://example.com>, <ftp://example.com/path>, <mailto:dylan@example.com>, <dylan@example.com> (auto-mailto).

Many links in one paragraph: [one](https://one.com), [two](https://two.com), [three](https://three.com), [four](https://four.com), [five](https://five.com) — five separate annotations.

A link with inline formatting in its text: [**bold** *italic* `code` mixed](https://example.com).

A link in a list item with surrounding text: see below.

- Plain item with no link
- Item containing [a link in the middle](https://example.com) of the sentence
- Item starting with [a link](https://example.com) at the start
- Item ending with [a link](https://example.com)

A link in a blockquote alongside other formatting:

> Quoted text with **bold** and *italic* and a [link](https://example.com) and `code` all together.

A link in a table cell:

| Resource | URL |
| -------- | --- |
| Homepage | [example.com](https://example.com) |
| Docs | [docs.example.com](https://docs.example.com/path/to/docs) |
| Repo | <https://github.com/eagredev/inkmd> |

Edge cases that should NOT become links:

- Just [text in brackets] with no parens
- [Half a link]( — unmatched paren
- An unmatched [opening bracket alone
- An autolink with [space inside](https://example.com/with space) URL
- A pseudo-autolink without scheme: <just text inside angles>

## Pagination check

The following paragraphs are repetitive on purpose — they should fill the rest of this page and push later content to subsequent pages. Each contains some inline formatting so that wrapping behavior across page breaks gets tested for styled runs as well as plain text.

Lorem ipsum **dolor** sit amet, consectetur *adipiscing* elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco `laboris` nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.

Lorem ipsum **dolor** sit amet, consectetur *adipiscing* elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco `laboris` nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.

Lorem ipsum **dolor** sit amet, consectetur *adipiscing* elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco `laboris` nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.

A heading that should ideally NOT be orphaned at the bottom of a page — it should bind visually to the body paragraph below it. (inkmd's current pagination doesn't prevent orphans, so this may show one.)

### Heading near a page boundary

Body paragraph immediately following the heading above. The heading should appear on the same page as this paragraph; if the heading is the last thing on a page and the body falls onto the next page, that's a known limitation worth noting.

## Whitespace and Unicode

A paragraph    with    multiple    spaces    between    words    (markdown collapses these).

A paragraph
with
soft
line
breaks
inside
(should join with spaces).

Typographic punctuation rendered via WinAnsi: em-dash —, en-dash –, single curly quotes 'one' and double curly "two", apostrophe in don't, ellipsis …, bullet character • (also used by lists).

Non-WinAnsi codepoints will render as `?` — that's a v0.1 limitation: 日本語 résumé piñata naïve.

A heading with curly quotes: "It's a test"
==========================================

## Mixing everything together

This final section combines structures into a nest of nests.

> A blockquote containing:
>
> ### A heading
>
> A paragraph with **bold**, *italic*, ~~struck~~, `code`, and [a link](https://example.com).
>
> - A list
> - Inside the quote
>     - With nested items
>         - And deeper nesting
>     - And [links](https://example.com) at depth
> - Back at the outer list level
>
> A code block inside the quote:
>
> ```python
> if True:
>     print("nested deep")
> ```
>
> A table inside the quote (probably won't render correctly — v0.1 limitation):
>
> | A | B |
> | --- | --- |
> | 1 | 2 |
>
> Closing paragraph of the quote.

End of torture test. If you've made it this far without a crash, that's a good sign.

## GFM autolinks (added 0.0.11.5)

This section tests bare URL and email detection. None of these use angle brackets or `[text](url)` syntax — they're just plain text that inkmd should auto-detect.

Visit https://example.com or http://example.com directly. Also try ftp://files.example.com.

The `www.` prefix works too: www.example.com gets the http:// prefix auto-added.

Email at dylan@example.com or alice@example.co.uk for support.

In a list:

- https://github.com is bare
- alice@example.com — email autolink
- See www.python.org for Python docs

In a blockquote:

> Visit https://example.com or email dylan@example.com to get involved.

In a table:

| Resource | Bare URL | Bare Email |
| -------- | -------- | ---------- |
| Home | https://example.com | hi@example.com |
| Docs | https://docs.example.com | docs@example.com |

Sentence-ending punctuation is stripped — these don't include the trailing punct: https://example.com. Yes, https://example.com, also https://example.com! Even with a semicolon: https://example.com;

But mid-URL punctuation is preserved: https://example.com/path?query=value&other=thing#section is one whole URL.

Balanced parens stay: see https://en.wikipedia.org/wiki/Foo_(bar) for the article.

Surrounding parens don't get eaten: (visit https://example.com).

Mid-word URLs stay literal: prefixedhttps://example.com is just text, and bareword.com without scheme is plain text.

Strict CommonMark mode (autolinks=False) would render these as plain text instead.
