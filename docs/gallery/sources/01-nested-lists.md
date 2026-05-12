# Nested lists

Lists nested deeper than typical, with mixed marker types per level. CommonMark allows arbitrary nesting; this probes how indentation, tight/loose distinction, and visual hierarchy survive at depth.

## Eight levels deep, mixed markers

- L1 unordered
  1. L2 ordered
     * L3 unordered (star marker)
       1. L4 ordered
          + L5 unordered (plus marker)
            1. L6 ordered
               - L7 unordered (dash marker)
                 1. L8 ordered — the deepest reasonable depth

The eighth level should still render at a sensible indent, not run off the page.

## Mixed loose and tight

This list mixes blank-line separation patterns.

1. First item, single line.
2. Second item, single line.

3. Third item, after a blank line — this is now loose.

4. Fourth item.
5. Fifth item, back to tight.

A loose item in the middle should make the entire list loose. If only the third item is loose-rendered, the renderer is doing the right thing on a technicality, but most renderers go all-or-nothing.

## Lists with paragraph continuation

- First item.

  This is a second paragraph of the same item, separated by a blank line and indented.

- Second item.

  Continuation.

  And another paragraph.

## Lists with embedded code

- Item one, prose.

  ```python
  def hello():
      print("nested in a list item")
  ```

  More prose after the code block.

- Item two.

## Lists with embedded quotes

- Item one.

  > A quote nested inside item one.
  >
  > Multi-line.

- Item two.

## Ordered list with arbitrary start

47. Item starting at 47.
48. Item 48.
49. Item 49.

100. Item starting at 100.
101. Item 101.

The renderer should honour the start number — these should not all renumber to 1.
