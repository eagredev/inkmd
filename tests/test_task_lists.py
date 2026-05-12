"""GFM task list tests (v0.2 feature).

A list item whose first paragraph starts with ``[ ]``, ``[x]``, or
``[X]`` followed by a space is a "task list item". The bracket prefix
is consumed by the parser; the item's ``task`` flag carries the state
(False unchecked, True checked, None for an ordinary list item).

References:
    - GFM 0.29 section 5.3
    - tests/conformance/run_gfm.py for spec-level tests
"""

from __future__ import annotations

import re

import inkmd
from inkmd.ast import List, ListItem, Paragraph, Text
from inkmd.parser import parse


def _first_list(md: str) -> List:
    doc = parse(md)
    assert isinstance(doc.blocks[0], List)
    return doc.blocks[0]


# --- Parser: task-flag detection ----------------------------------------


def test_unchecked_task_sets_flag_false():
    lst = _first_list("- [ ] do this")
    item = lst.items[0]
    assert item.task is False


def test_checked_task_sets_flag_true():
    lst = _first_list("- [x] done")
    item = lst.items[0]
    assert item.task is True


def test_checked_uppercase_x_also_counts():
    lst = _first_list("- [X] also done")
    item = lst.items[0]
    assert item.task is True


def test_non_task_item_has_task_none():
    lst = _first_list("- ordinary item")
    item = lst.items[0]
    assert item.task is None


def test_task_prefix_stripped_from_paragraph():
    lst = _first_list("- [x] do laundry")
    item = lst.items[0]
    para = item.blocks[0]
    assert isinstance(para, Paragraph)
    assert para.inlines == (Text("do laundry"),)


def test_unchecked_prefix_stripped_from_paragraph():
    lst = _first_list("- [ ] write tests")
    item = lst.items[0]
    para = item.blocks[0]
    assert isinstance(para, Paragraph)
    assert para.inlines == (Text("write tests"),)


def test_only_first_paragraph_examined():
    """A `[ ]` later in the same item is text, not a task marker."""
    src = "- ordinary\n\n  [ ] not a task"
    lst = _first_list(src)
    item = lst.items[0]
    assert item.task is None


def test_no_space_after_bracket_means_not_a_task():
    """`[x]bar` (no space) is literal text, not a task prefix."""
    lst = _first_list("- [x]bar")
    item = lst.items[0]
    assert item.task is None


def test_mixed_task_and_non_task_in_same_list():
    src = "- [x] done\n- [ ] pending\n- ordinary"
    lst = _first_list(src)
    assert lst.items[0].task is True
    assert lst.items[1].task is False
    assert lst.items[2].task is None


def test_nested_task_lists():
    src = "- [x] parent\n  - [ ] child1\n  - [x] child2\n- [ ] sibling"
    lst = _first_list(src)
    # Outer
    assert lst.items[0].task is True
    assert lst.items[1].task is False
    # Inner: parent's first non-paragraph block is the nested list.
    inner = lst.items[0].blocks[1]
    assert isinstance(inner, List)
    assert inner.items[0].task is False
    assert inner.items[1].task is True


# --- End-to-end PDF render ----------------------------------------------


def _ascii_text(pdf: bytes) -> str:
    """Coarse extract of visible ASCII text from PDF output."""
    return b"".join(re.findall(rb"\(([^)\\]+)\)", pdf)).decode(
        "latin-1", errors="replace"
    )


def test_pdf_renders_checked_box_for_checked_task():
    pdf = inkmd.compile("- [x] go for run")
    text = _ascii_text(pdf)
    assert "[x]" in text


def test_pdf_renders_empty_box_for_unchecked_task():
    pdf = inkmd.compile("- [ ] cook dinner")
    text = _ascii_text(pdf)
    assert "[ ]" in text


def test_pdf_does_not_render_box_for_ordinary_item():
    pdf = inkmd.compile("- ordinary item")
    text = _ascii_text(pdf)
    # The bullet should be present, not a checkbox.
    assert "[ ]" not in text
    assert "[x]" not in text
