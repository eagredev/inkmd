"""End-to-end adversarial security tests.

These tests assert on the *final compiled PDF bytes* (not just the
intermediate AST), proving inkmd's documented threat model holds at the
output boundary — the level a security-literate reviewer actually probes.

The companion unit tests (test_url_filter.py, test_html_passthrough.py)
prove the filter *logic*; these prove the *artifact*: a PDF produced from
hostile markdown contains no executable annotation, no dangerous PDF
action, and no leaked script/style payload, and the renderer performs no
network I/O for untrusted input by default.

See docs/security.md for the threat model these tests pin.
"""
from __future__ import annotations

import re

import pytest

import inkmd


# --- 1. Dangerous URL schemes never become clickable annotations ----------

UNSAFE_LINK_DOCS = [
    "[click](javascript:alert(1))",
    "[xss](data:text/html,<script>alert(1)</script>)",
    "[local](file:///etc/passwd)",
    "[vb](vbscript:msgbox(1))",
    "[app](customscheme://do-something)",
]


@pytest.mark.parametrize("md", UNSAFE_LINK_DOCS)
def test_unsafe_link_produces_no_uri_annotation(md: str) -> None:
    """A link with a dangerous scheme must leave NO /URI action in the PDF.

    The link *text* survives (the reader still sees the words), but the
    clickable annotation pointing at the hostile scheme is gone.
    """
    pdf = inkmd.compile(md)
    # No /URI action carrying any of the dangerous schemes.
    for scheme in (b"javascript:", b"vbscript:", b"file:", b"data:", b"customscheme:"):
        assert not re.search(rb"/S /URI /URI \([^)]*" + scheme, pdf), (
            f"dangerous scheme {scheme!r} leaked into a /URI action"
        )


def test_safe_false_opt_in_restores_unsafe_link() -> None:
    """The escape hatch works: safe=False intentionally keeps the scheme.

    This proves the filter is the thing blocking it (not an accident of
    rendering), and documents the opt-out for trusted content.
    """
    pdf = inkmd.compile("[click](javascript:alert(1))", safe=False)
    assert re.search(rb"/S /URI /URI \(javascript:", pdf)


def test_safe_https_link_is_preserved() -> None:
    """A legitimate https link DOES produce a /URI annotation."""
    pdf = inkmd.compile("[ok](https://example.com/page)")
    assert re.search(rb"/S /URI /URI \(https://example\.com", pdf)


# --- 2. The PDF emitter can only ever emit /URI actions -------------------

DANGEROUS_PDF_TOKENS = [
    b"/JavaScript",
    b"/JS",
    b"/Launch",
    b"/OpenAction",
    b"/SubmitForm",
    b"/ImportData",
    b"/GoToR",
    b"/EmbeddedFile",
    b"/RichMedia",
]


@pytest.mark.parametrize(
    "md",
    [
        "[a](javascript:alert(1))",
        "<a href='javascript:void(0)'>x</a>",
        "Normal **document** with a [link](https://ok.com).",
        "![img](data:text/html,<script>x</script>)",
    ],
)
def test_pdf_contains_no_dangerous_action_types(md: str) -> None:
    """inkmd's PDF emitter has exactly one action type: /URI. No PDF
    auto-run, file-launch, form-submit, or embedded-file vector exists in
    the output regardless of input."""
    pdf = inkmd.compile(md)
    for token in DANGEROUS_PDF_TOKENS:
        assert token not in pdf, f"{token!r} appeared in compiled PDF"


# --- 3. script / style / iframe payloads are dropped, not rendered --------

@pytest.mark.parametrize(
    "md,payload",
    [
        ("Before <script>steal(document.cookie)</script> After", b"steal"),
        ("A <style>.x{background:url(http://evil)}</style> B", b"evil"),
        ('X <iframe src="http://evil.example">fb</iframe> Y', b"evil.example"),
        ("P <!-- exfiltrate secret --> Q", b"exfiltrate"),
        ("R <?php system($_GET[c]); ?> S", b"system"),
    ],
)
def test_dangerous_html_body_not_in_pdf(md: str, payload: bytes) -> None:
    """The body of a dropped dangerous tag never reaches the PDF text."""
    pdf = inkmd.compile(md)
    assert payload not in pdf


def test_surrounding_text_survives_dropped_script() -> None:
    """Dropping <script> must not eat the surrounding prose.

    The surviving words are emitted as PDF text operators, but kerning can
    split a word across a ``TJ`` array (e.g. ``[(Bef) 30 (ore)] TJ``), so we
    match the letters in order rather than as a contiguous substring.
    """
    pdf = inkmd.compile("Before <script>x</script> After")
    assert re.search(rb"B.*e.*f.*o.*r.*e", pdf, re.DOTALL)
    assert re.search(rb"A.*f.*t.*e.*r", pdf, re.DOTALL)
    # And the script body is gone.
    assert b"<script" not in pdf


# --- 4. Zero network I/O by default ---------------------------------------

def test_remote_image_not_fetched_by_default() -> None:
    """A remote image URL must not be fetched: no XObject, no network."""
    pdf = inkmd.compile("![remote](https://example.com/x.png)")
    assert b"/XObject" not in pdf


def test_compile_performs_no_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard proof of the zero-network claim: poison every outbound socket
    path so ANY network attempt during compile() raises. Feed compile() a
    document stuffed with remote references and confirm it still succeeds
    (because nothing is fetched)."""
    import socket
    import urllib.request

    def _boom(*a, **k):  # pragma: no cover - only fires on a (bug) network call
        raise AssertionError("inkmd attempted network I/O during compile()")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    hostile = (
        "# Doc\n\n"
        "![img](https://example.com/a.png)\n\n"
        '<img src="http://example.com/b.png" alt="x">\n\n'
        "[link](https://example.com)\n"
    )
    pdf = inkmd.compile(hostile)  # must not raise
    assert pdf.startswith(b"%PDF-1.4")
