# Table edge cases

GFM tables look simple but have several edge cases: ragged rows, alignment markers, escaped pipes, very wide and very narrow tables, and inline formatting in cells.

## Minimal table

| a | b |
|---|---|
| 1 | 2 |

## Wide table — 8 columns

| col1 | col2 | col3 | col4 | col5 | col6 | col7 | col8 |
|------|------|------|------|------|------|------|------|
| a    | b    | c    | d    | e    | f    | g    | h    |
| 1    | 2    | 3    | 4    | 5    | 6    | 7    | 8    |

Should fit on a letter page in a sensible width or wrap gracefully.

## Alignments

| Left | Centre | Right |
|:-----|:------:|------:|
| L1   | C1     | R1    |
| L2 long content | C2 | R2 short |
| short L3 | C3 longer | 12345 |

The first column should be left-aligned, the second centred, the third right-aligned.

## Ragged rows

| a | b | c |
|---|---|---|
| 1 |   | 3 |
| 1 | 2 |   |
|   | 2 |   |
| 1 | 2 | 3 | extra ignored |

The last row should drop the extra cell; the shorter rows should pad with empty cells.

## Inline formatting in cells

| Style | Example |
|-------|---------|
| bold | **value** |
| italic | *value* |
| code | `value` |
| link | [click](https://example.com) |
| mixed | **bold *italic `code`*** |

## Escaped pipes inside cells

| a | b \| c | d |
|---|--------|---|
| 1 | with \| pipe | 3 |

The `\|` should render as a literal pipe character, not a column separator.

## Very long content in one cell

| short | long |
|-------|------|
| hi | This cell has a paragraph of content that may overflow the column width depending on how the renderer balances columns. It might wrap, it might shrink the other column, or it might overflow. |
| ok | Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. |

## Table at the bottom of a page

This is filler to push the table down. Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.

| only | one |
|------|-----|
| row  | here |
