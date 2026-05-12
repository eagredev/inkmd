# Mixed block transitions

Where one block type ends and another begins is a fertile place for parser bugs. This gallery walks every adjacent pair: paragraph-to-list, list-to-code, code-to-quote, quote-to-table, table-to-paragraph.

## Paragraph to fenced code

A paragraph immediately before a fenced code block.
```python
print("the line above ends with a sentence")
```
A paragraph immediately after.

## Heading to code

### Heading
```
Bare code block right after heading
```

## List to code

- Item one
- Item two
```python
print("a code block immediately after a list")
```

The code should NOT be absorbed into the second list item; it should be a separate block.

## Code to list

```python
print("end of code")
```
- Item one
- Item two

## Quote to table

> A quote that ends here.

| immediately | followed |
|------------|----------|
| by | a table |

## Table to quote

| a | b |
|---|---|
| 1 | 2 |

> A quote immediately after a table.

## Paragraph to thematic break

A paragraph of content.

---

Another paragraph after the break.

## Thematic break adjacent to heading

---

# Heading right after a break

Body text.

## Tight transitions

End of paragraph 1.
- list item starts right after a line of paragraph 1

The above might or might not work — strict CommonMark says it should; many parsers require a blank line. We render it as if there were a blank line if we detect a list marker at column zero.

## Quote nested in list, code nested in quote

- Outer list item.

  > Quote nested in the item.
  >
  > ```python
  > print("code nested in the quote in the list")
  > ```
  >
  > End of quote.

- Second outer item.
