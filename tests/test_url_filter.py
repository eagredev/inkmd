"""URL-scheme filter tests.

The v0.2 filter strips link annotations whose URL scheme is not on
the safe allow-list. Link text survives; the /URI annotation does
not. The opt-out (``safe=False``) restores v0.1 behaviour.

References:
    - docs/security.md (v0.1 finding + v0.2 plan)
    - src/inkmd/url_filter.py (the implementation)
"""

from __future__ import annotations

import re

import inkmd
from inkmd.ast import AutoLink, Document, Link, Paragraph, Text
from inkmd.url_filter import SAFE_SCHEMES, filter_document, is_safe_url


# --- is_safe_url unit checks ----------------------------------------------


def test_is_safe_url_http_allowed():
    assert is_safe_url("http://example.com")
    assert is_safe_url("https://example.com/path?q=1")


def test_is_safe_url_mailto_tel_allowed():
    assert is_safe_url("mailto:foo@bar.baz")
    assert is_safe_url("tel:+1-555-0100")


def test_is_safe_url_ftp_xmpp_allowed():
    assert is_safe_url("ftp://example.com/file")
    assert is_safe_url("xmpp:user@server")


def test_is_safe_url_javascript_blocked():
    assert not is_safe_url("javascript:alert(1)")
    assert not is_safe_url("JavaScript:void(0)")


def test_is_safe_url_data_blocked():
    assert not is_safe_url("data:text/html,<script>x</script>")


def test_is_safe_url_vbscript_file_blocked():
    assert not is_safe_url("vbscript:msgbox(1)")
    assert not is_safe_url("file:///etc/passwd")


def test_is_safe_url_custom_scheme_blocked():
    assert not is_safe_url("steam://run/12345")
    assert not is_safe_url("ms-msdt://debug")


def test_is_safe_url_relative_and_fragment_allowed():
    """No scheme = no navigation out of document = safe."""
    assert is_safe_url("#section")
    assert is_safe_url("/absolute/path")
    assert is_safe_url("relative/path.html")
    assert is_safe_url("")


def test_is_safe_url_with_unusual_case():
    assert is_safe_url("HTTPS://example.com")
    assert is_safe_url("MailTo:foo@bar.baz")


def test_safe_schemes_match_docs():
    """The allow-list documented in security.md should match the code."""
    assert SAFE_SCHEMES == frozenset({"http", "https", "mailto", "tel", "ftp", "xmpp"})


# --- AST filter unit checks ------------------------------------------------


def test_filter_document_safe_false_returns_unchanged():
    md_doc = Document(blocks=(Paragraph(
        inlines=(Link(inlines=(Text("x"),), url="javascript:1"),)
    ),))
    out = filter_document(md_doc, safe=False)
    assert out is md_doc


def test_filter_document_strips_unsafe_link():
    md_doc = Document(blocks=(Paragraph(
        inlines=(
            Text("Click "),
            Link(inlines=(Text("here"),), url="javascript:alert(1)"),
            Text(" please."),
        ),
    ),))
    out = filter_document(md_doc, safe=True)
    para = out.blocks[0]
    # Link gone; children inlined.
    assert not any(isinstance(n, Link) for n in para.inlines)
    text = "".join(n.content for n in para.inlines if isinstance(n, Text))
    assert text == "Click here please."


def test_filter_document_preserves_safe_link():
    md_doc = Document(blocks=(Paragraph(
        inlines=(Link(inlines=(Text("ok"),), url="https://example.com"),),
    ),))
    out = filter_document(md_doc, safe=True)
    links = [n for n in out.blocks[0].inlines if isinstance(n, Link)]
    assert len(links) == 1
    assert links[0].url == "https://example.com"


def test_filter_document_demotes_unsafe_autolink_to_text():
    md_doc = Document(blocks=(Paragraph(
        inlines=(AutoLink(url="javascript:alert(1)", text="javascript:alert(1)"),),
    ),))
    out = filter_document(md_doc, safe=True)
    inlines = out.blocks[0].inlines
    assert len(inlines) == 1
    assert isinstance(inlines[0], Text)
    assert inlines[0].content == "javascript:alert(1)"


def test_filter_document_preserves_safe_autolink():
    md_doc = Document(blocks=(Paragraph(
        inlines=(AutoLink(url="https://example.com", text="https://example.com"),),
    ),))
    out = filter_document(md_doc, safe=True)
    inlines = out.blocks[0].inlines
    assert len(inlines) == 1
    assert isinstance(inlines[0], AutoLink)


# --- End-to-end PDF emission ----------------------------------------------


def _uris(pdf_bytes: bytes) -> list[bytes]:
    """Extract all /URI annotation values from a PDF."""
    return re.findall(rb"/URI \(([^)]+)\)", pdf_bytes)


def test_compile_default_filters_javascript():
    pdf = inkmd.compile("[click](javascript:alert(1))")
    assert _uris(pdf) == []


def test_compile_default_filters_data():
    pdf = inkmd.compile("[xss](data:text/html,foo)")
    assert _uris(pdf) == []


def test_compile_default_filters_file():
    pdf = inkmd.compile("[local](file:///etc/passwd)")
    assert _uris(pdf) == []


def test_compile_default_keeps_https():
    pdf = inkmd.compile("[ok](https://example.com)")
    assert _uris(pdf) == [b"https://example.com"]


def test_compile_default_keeps_mailto_tel():
    pdf = inkmd.compile("[a](mailto:x@y.z) and [b](tel:+1234)")
    uris = _uris(pdf)
    assert b"mailto:x@y.z" in uris
    assert b"tel:+1234" in uris


def test_compile_safe_false_keeps_javascript():
    pdf = inkmd.compile("[click](javascript:alert(1))", safe=False)
    uris = _uris(pdf)
    # PDF escapes parens in the URI string, so check by prefix.
    assert any(u.startswith(b"javascript:") for u in uris)


def test_compile_filters_bare_javascript_autolink():
    pdf = inkmd.compile("<javascript:alert(1)>")
    assert _uris(pdf) == []


# --- Regression: deeply-nested containers must not blow the stack ---------


def test_filter_handles_deeply_nested_blockquotes():
    """A 10000-deep blockquote chain must filter without RecursionError.

    The first cut of the filter was naively recursive and overflowed
    Python's stack on this input. The parser itself handles this depth
    fine; the filter must not pessimise that. See tests/conformance/
    resource_probe.py for the wider pathological-input survey.
    """
    import sys
    sys.setrecursionlimit(50_000)
    md = ">" * 10_000 + " hi"
    # Just calling compile() exercises the filter. The test passes if
    # this returns at all.
    pdf = inkmd.compile(md)
    assert pdf.startswith(b"%PDF-")
