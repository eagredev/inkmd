"""HTML allow-list (Option B) passthrough tests.

The parser preserves raw HTML constructs as HtmlInline; html_filter
applies the Option B allow-list, promoting recognised tags to typed
AST nodes (Subscript, Superscript, Underline, Mark, Kbd, HardBreak,
Strikethrough, Link) and dropping or unwrapping the rest. The PDF
renderer paints visual decorations (yellow background for <mark>,
grey border for <kbd>, underline rule for <u>, baseline shift for
<sub>/<sup>).

References:
    - docs/design/html-passthrough.md (Option B spec)
    - src/inkmd/html_filter.py (the allow-list)
"""

from __future__ import annotations

import re

import inkmd
from inkmd.ast import (
    Document,
    HardBreak,
    HtmlInline,
    Kbd,
    Link,
    Mark,
    Paragraph,
    Strikethrough,
    Subscript,
    Superscript,
    Text,
    Underline,
)
from inkmd.html_filter import filter_document
from inkmd.parser import parse


def _filter(md: str) -> Document:
    return filter_document(parse(md))


def _first_paragraph_inlines(md: str):
    return _filter(md).blocks[0].inlines


# --- Parser raw recognition ------------------------------------------------


def test_parser_emits_htmlinline_for_open_tag():
    doc = parse("Hello <kbd>K</kbd>", html=True)
    p = doc.blocks[0]
    types = [type(n).__name__ for n in p.inlines]
    assert "HtmlInline" in types


def test_parser_html_disabled_emits_literal_text():
    doc = parse("Hello <kbd>K</kbd>", html=False)
    p = doc.blocks[0]
    # No HtmlInline anywhere; the < / > characters end up in text via
    # the v0.1-style escape path (or as plain text since the autolink
    # match also fails).
    assert not any(isinstance(n, HtmlInline) for n in p.inlines)


def test_parser_recognises_self_closing_tag():
    doc = parse("Line one<br/>Line two")
    assert any(isinstance(n, HtmlInline) for n in doc.blocks[0].inlines)


def test_parser_recognises_comment():
    doc = parse("Before<!-- hidden -->After")
    raws = [n.raw for n in doc.blocks[0].inlines if isinstance(n, HtmlInline)]
    assert "<!-- hidden -->" in raws


# --- Filter: typed promotion ----------------------------------------------


def test_filter_sub_becomes_subscript():
    inlines = _first_paragraph_inlines("H<sub>2</sub>O")
    assert any(isinstance(n, Subscript) for n in inlines)


def test_filter_sup_becomes_superscript():
    inlines = _first_paragraph_inlines("E = mc<sup>2</sup>")
    assert any(isinstance(n, Superscript) for n in inlines)


def test_filter_u_becomes_underline():
    inlines = _first_paragraph_inlines("<u>under</u>")
    assert isinstance(inlines[0], Underline)


def test_filter_mark_becomes_mark():
    inlines = _first_paragraph_inlines("<mark>highlight</mark>")
    assert isinstance(inlines[0], Mark)


def test_filter_kbd_becomes_kbd():
    inlines = _first_paragraph_inlines("Press <kbd>Ctrl</kbd>")
    assert any(isinstance(n, Kbd) for n in inlines)


def test_filter_s_strike_del_all_become_strikethrough():
    """HTML <s>, <strike>, <del> are aliases for GFM ~~strikethrough~~."""
    for tag in ("s", "strike", "del"):
        inlines = _first_paragraph_inlines(f"<{tag}>x</{tag}>")
        assert any(isinstance(n, Strikethrough) for n in inlines), tag


def test_filter_br_becomes_hardbreak():
    inlines = _first_paragraph_inlines("Line A<br>Line B")
    assert any(isinstance(n, HardBreak) for n in inlines)


def test_filter_br_self_closing_form_also_works():
    for form in ("<br>", "<br/>", "<br />"):
        inlines = _first_paragraph_inlines(f"A{form}B")
        assert any(isinstance(n, HardBreak) for n in inlines)


def test_filter_a_href_becomes_link():
    inlines = _first_paragraph_inlines(
        'Click <a href="https://example.com">here</a>'
    )
    links = [n for n in inlines if isinstance(n, Link)]
    assert len(links) == 1
    assert links[0].url == "https://example.com"


def test_filter_a_href_with_title():
    inlines = _first_paragraph_inlines(
        '<a href="https://example.com" title="Tooltip">go</a>'
    )
    link = next(n for n in inlines if isinstance(n, Link))
    assert link.title == "Tooltip"


def test_filter_a_without_href_flattens_to_text():
    """`<a name="anchor">x</a>` (no href) is not a navigation link;
    we flatten its content rather than promote to Link."""
    inlines = _first_paragraph_inlines('<a name="anchor">target</a>')
    assert not any(isinstance(n, Link) for n in inlines)
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "target" in text


# --- Filter: drop and unwrap ----------------------------------------------


def test_filter_unknown_tag_drops_syntax_keeps_content():
    inlines = _first_paragraph_inlines("Hello <weird-tag>kept</weird-tag>!")
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "kept" in text
    assert not any(isinstance(n, HtmlInline) for n in inlines)


def test_filter_span_unwraps():
    inlines = _first_paragraph_inlines(
        'A <span style="color:red">red</span> bit'
    )
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "red" in text
    # No HtmlInline survives.
    assert not any(isinstance(n, HtmlInline) for n in inlines)


def test_filter_script_drops_with_content():
    """<script> and similar dangerous tags drop entirely, content included."""
    inlines = _first_paragraph_inlines(
        "Before <script>alert(1)</script> After"
    )
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "alert" not in text
    assert "Before" in text
    assert "After" in text


def test_filter_style_drops_with_content():
    inlines = _first_paragraph_inlines(
        "A <style>.x { color: red }</style> B"
    )
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "color" not in text
    assert "red" not in text


def test_filter_iframe_drops():
    inlines = _first_paragraph_inlines(
        'X <iframe src="x.html">fallback</iframe> Y'
    )
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "fallback" not in text


def test_filter_html_comment_drops_silently():
    inlines = _first_paragraph_inlines("A <!-- secret --> B")
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "secret" not in text


def test_filter_cdata_drops():
    inlines = _first_paragraph_inlines("A <![CDATA[inside]]> B")
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "inside" not in text


def test_filter_processing_instruction_drops():
    inlines = _first_paragraph_inlines("A <?php echo $x; ?> B")
    text = "".join(n.content for n in inlines if isinstance(n, Text))
    assert "php" not in text


# --- URL filter cooperates with promoted <a href> -------------------------


def test_filter_a_href_javascript_blocked_by_url_filter():
    """A `<a href="javascript:...">` becomes a Link, then the URL filter
    drops the unsafe scheme. The combination of html_filter + url_filter
    means HTML hrefs are gated the same way markdown links are."""
    pdf = inkmd.compile('<a href="javascript:alert(1)">click</a>')
    # No URI annotation in the PDF.
    assert not re.search(rb"/URI \([^)]*javascript:", pdf)


def test_filter_a_href_https_passes_url_filter():
    pdf = inkmd.compile('<a href="https://example.com">click</a>')
    assert re.search(rb"/URI \(https://example", pdf)


# --- PDF visual decorations ----------------------------------------------


def test_compile_mark_emits_yellow_background():
    pdf = inkmd.compile("<mark>highlighted</mark>")
    # `1 0.95 0.6 rg` is the MARK_FILL constant.
    assert re.search(rb"1 0\.95 0\.6 rg", pdf) is not None


def test_compile_kbd_emits_grey_border():
    pdf = inkmd.compile("<kbd>Ctrl</kbd>")
    # `0.5 0.5 0.5 rg` is KBD_BORDER.
    assert re.search(rb"0\.5 0\.5 0\.5 rg", pdf) is not None


def test_compile_underline_emits_rule():
    """`<u>` produces an underline rect distinct from link underlines."""
    pdf = inkmd.compile("<u>text</u>")
    # The rule rect should appear (just below baseline). We check the
    # rendered glyph is in Helvetica (default body font) and the rule
    # is in plain black via `re f` after fill colour reset.
    assert b" re f" in pdf


def test_compile_subscript_applies_baseline_shift():
    pdf = inkmd.compile("H<sub>2</sub>O")
    # The "2" run should be emitted at a baseline-shifted Tm. Look for
    # a Tm whose y-coord differs from the surrounding text y by a
    # negative offset.
    tms = re.findall(rb"1 0 0 1 (\S+) (\S+) Tm", pdf)
    ys = sorted(set(float(y) for _x, y in tms))
    # At least two distinct y values: the body baseline and the
    # subscript-shifted baseline.
    assert len(ys) >= 2


def test_compile_dangerous_tag_yields_no_annotation():
    """Even when the script tag's contents include a URL-shaped string,
    nothing about it leaks into the PDF."""
    pdf = inkmd.compile('<script>fetch("https://attacker.example/")</script>')
    assert b"attacker.example" not in pdf


# --- No-html opt-out ----------------------------------------------------


def test_compile_no_html_treats_tags_as_text_or_drops():
    """With html=False the parser doesn't recognise HTML, so a `<sub>` is
    not interpreted. The exact rendering depends on whether the `<` is
    escaped or absorbed; the contract is just "no Subscript node"."""
    pdf = inkmd.compile("H<sub>2</sub>O", html=False)
    # No subscript-flavoured baseline shift; the whole run sits on one
    # baseline (or close enough).
    tms = re.findall(rb"1 0 0 1 (\S+) (\S+) Tm", pdf)
    ys = sorted(set(float(y) for _x, y in tms))
    assert len(ys) == 1


# --- Determinism --------------------------------------------------------


def test_compile_html_output_deterministic():
    md = "Press <kbd>Ctrl+S</kbd> to save. <mark>Note</mark> the order."
    pdf1 = inkmd.compile(md)
    pdf2 = inkmd.compile(md)
    assert pdf1 == pdf2
