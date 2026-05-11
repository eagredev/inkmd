"""GFM autolink tests — milestone 0.0.11.5.

GFM autolinks detect bare URLs and email addresses without requiring
angle brackets. Enabled by default; disable with ``parse(autolinks=False)``
or ``compile(md, autolinks=False)``.
"""

from __future__ import annotations

import inkmd
from inkmd.ast import AutoLink, Emphasis, Link, Paragraph, Text
from inkmd.parser import parse


def _inlines(md: str, **kwargs):
    doc = parse(md, **kwargs)
    return doc.blocks[0].inlines


# --- Bare URL detection -----------------------------------------------------


def test_bare_https_at_start_is_autolink():
    inlines = _inlines("https://example.com")
    assert inlines == (AutoLink(url="https://example.com"),)


def test_bare_http_inline():
    inlines = _inlines("Visit http://example.com today.")
    assert inlines == (
        Text("Visit "),
        AutoLink(url="http://example.com"),
        Text(" today."),
    )


def test_bare_ftp_inline():
    inlines = _inlines("Try ftp://files.example.com/path here.")
    assert inlines == (
        Text("Try "),
        AutoLink(url="ftp://files.example.com/path"),
        Text(" here."),
    )


def test_www_prefix_gets_http_added():
    inlines = _inlines("Site at www.example.com online.")
    assert inlines == (
        Text("Site at "),
        AutoLink(url="http://www.example.com"),
        Text(" online."),
    )


def test_multiple_urls_in_one_paragraph():
    inlines = _inlines(
        "Try https://a.com, http://b.com, and ftp://c.com end."
    )
    autolinks = [i for i in inlines if isinstance(i, AutoLink)]
    assert [a.url for a in autolinks] == [
        "https://a.com",
        "http://b.com",
        "ftp://c.com",
    ]


# --- Trailing punctuation ---------------------------------------------------


def test_trailing_period_stripped():
    """Sentence-ending period after URL stays as text, not in the URL."""
    inlines = _inlines("End at https://example.com.")
    assert inlines == (
        Text("End at "),
        AutoLink(url="https://example.com"),
        Text("."),
    )


def test_trailing_comma_stripped():
    inlines = _inlines("https://example.com, and more")
    assert inlines[0].url == "https://example.com"


def test_trailing_question_mark_stripped():
    """A `?` at the end of a sentence comes off — but a `?` mid-URL stays."""
    inlines = _inlines("See https://example.com/foo?bar=1 here.")
    auto = [i for i in inlines if isinstance(i, AutoLink)][0]
    # The mid-URL ?bar=1 stays; the period at the end is stripped.
    assert auto.url == "https://example.com/foo?bar=1"


def test_balanced_parens_kept_in_url():
    """URL ending in `(bar)` keeps the balanced parens."""
    inlines = _inlines(
        "See https://en.wikipedia.org/wiki/Foo_(bar) for more."
    )
    auto = [i for i in inlines if isinstance(i, AutoLink)][0]
    assert auto.url == "https://en.wikipedia.org/wiki/Foo_(bar)"


def test_url_in_outer_parens_does_not_eat_closing_paren():
    """`(see https://example.com)` — the surrounding `)` stays outside."""
    inlines = _inlines("(see https://example.com)")
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "https://example.com"


# --- Email autolinks --------------------------------------------------------


def test_bare_email_gets_mailto():
    inlines = _inlines("Reach me at dylan@example.com please.")
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "mailto:dylan@example.com"


def test_email_with_trailing_period():
    inlines = _inlines("Email dylan@example.com.")
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "mailto:dylan@example.com"


def test_multiple_emails_in_one_paragraph():
    inlines = _inlines("alice@a.com, bob@b.com and carol@c.com end.")
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert [a.url for a in autos] == [
        "mailto:alice@a.com",
        "mailto:bob@b.com",
        "mailto:carol@c.com",
    ]


def test_email_with_plus_and_dots():
    inlines = _inlines("Filter: dylan+tag@example.co.uk here.")
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "mailto:dylan+tag@example.co.uk"


# --- Negative cases (should NOT autolink) ----------------------------------


def test_mid_word_url_not_autolinked():
    """`thishttps://example.com` mid-word stays as plain text."""
    inlines = _inlines("thishttps://example.com is mid-word")
    assert all(not isinstance(i, AutoLink) for i in inlines)


def test_scheme_with_no_host_dot_not_autolinked():
    """`https://localhost` (no dot in host) — not a GFM autolink."""
    inlines = _inlines("Run https://localhost here.")
    assert all(not isinstance(i, AutoLink) for i in inlines)


def test_bare_word_with_dot_not_autolinked():
    """`example.com` without scheme or `www.` prefix isn't autolinked."""
    inlines = _inlines("Visit example.com today.")
    assert all(not isinstance(i, AutoLink) for i in inlines)


def test_email_with_no_dot_in_domain_not_autolinked():
    inlines = _inlines("user@localhost is not email")
    assert all(not isinstance(i, AutoLink) for i in inlines)


# --- Interaction with other constructs ------------------------------------


def test_autolinks_disabled_inside_link_text():
    """`[click https://example.com here](url)` — inner URL stays as text."""
    inlines = _inlines("[click https://example.com here](https://other.com)")
    assert len(inlines) == 1
    link = inlines[0]
    assert isinstance(link, Link)
    assert link.url == "https://other.com"
    # The inner URL should be plain text, NOT an AutoLink.
    assert all(not isinstance(i, AutoLink) for i in link.inlines)


def test_autolink_in_list_item():
    inlines_doc = parse("- See https://example.com please")
    item = inlines_doc.blocks[0].items[0]
    para = item.blocks[0]
    autos = [i for i in para.inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "https://example.com"


def test_autolink_in_blockquote():
    doc = parse("> Visit https://example.com today")
    quote = doc.blocks[0]
    para = quote.blocks[0]
    autos = [i for i in para.inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "https://example.com"


def test_autolink_in_table_cell():
    md = "| URL |\n| --- |\n| https://example.com |"
    doc = parse(md)
    cell = doc.blocks[0].rows[0][0]
    autos = [i for i in cell.inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "https://example.com"


def test_autolink_after_emphasis():
    """Autolinks fire after a `*` closes an emphasis run (soft boundary)."""
    inlines = _inlines("*emph* then https://example.com end.")
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "https://example.com"


# --- Opt-out ----------------------------------------------------------------


def test_autolinks_false_disables_url_detection():
    """`parse(md, autolinks=False)` falls back to strict CommonMark."""
    inlines = _inlines("Visit https://example.com today.", autolinks=False)
    assert all(not isinstance(i, AutoLink) for i in inlines)


def test_autolinks_false_disables_email_detection():
    inlines = _inlines("Email dylan@example.com please.", autolinks=False)
    assert all(not isinstance(i, AutoLink) for i in inlines)


def test_autolinks_false_keeps_explicit_angle_form():
    """`<url>` still works when autolinks=False."""
    inlines = _inlines("Visit <https://example.com> today.", autolinks=False)
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "https://example.com"


def test_compile_autolinks_false_kwarg():
    """The public `compile()` accepts the same kwarg."""
    out_default = inkmd.compile("Visit https://example.com.")
    out_strict = inkmd.compile("Visit https://example.com.", autolinks=False)
    # Default emits a Link annotation; strict does not.
    assert b"/Subtype /Link" in out_default
    assert b"/Subtype /Link" not in out_strict


# --- End-to-end via compile() ---------------------------------------------


def test_compile_autolinks_emit_annotations():
    out = inkmd.compile("Visit https://example.com today.")
    assert b"/Subtype /Link" in out
    assert b"https://example.com" in out


def test_compile_email_autolink_emits_mailto_annotation():
    out = inkmd.compile("Email dylan@example.com please.")
    assert b"mailto:dylan@example.com" in out


# --- Bare host.tld/path (CV-style URLs) ----------------------------------
#
# Added 0.0.11.3 after CV mobile render showed `linkedin.com/in/dylanmoir`
# stayed black/plain. Strict GFM doesn't link these — but real-world docs
# (especially CVs and emails) need them. The path requirement keeps false
# positives like `e.g.` and `Mr. Smith` safe.


def test_bare_host_with_path_is_autolinked():
    inlines = _inlines("linkedin.com/in/dylanmoir")
    assert inlines == (AutoLink(url="http://linkedin.com/in/dylanmoir"),)


def test_bare_host_with_path_inline():
    inlines = _inlines("see github.com/eagredev for code")
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "http://github.com/eagredev"


def test_cv_header_line_all_three_links():
    """A line from a CV with email, LinkedIn, GitHub — all should link."""
    md = "Email | eagre.dev@gmail.com | linkedin.com/in/dylan | github.com/dylan"
    inlines = _inlines(md)
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    urls = [a.url for a in autos]
    assert "mailto:eagre.dev@gmail.com" in urls
    assert "http://linkedin.com/in/dylan" in urls
    assert "http://github.com/dylan" in urls


def test_bare_host_without_path_not_linked():
    """`linkedin.com` alone (no path) stays as text — avoids ambiguity."""
    inlines = _inlines("Just linkedin.com without path")
    assert all(not isinstance(i, AutoLink) for i in inlines)


def test_abbreviation_not_linked():
    """`e.g.`, `i.e.`, `Mr. Smith`, `Inc.` etc. must NOT autolink."""
    for src in ("e.g. example", "i.e. another", "Mr. Smith", "Inc. of"):
        inlines = _inlines(src)
        assert all(not isinstance(i, AutoLink) for i in inlines), src


def test_bare_host_trailing_period_stripped():
    inlines = _inlines("Visit linkedin.com/in/dylanmoir.")
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "http://linkedin.com/in/dylanmoir"


def test_bare_host_in_parens():
    inlines = _inlines("See (github.com/eagredev) for code.")
    autos = [i for i in inlines if isinstance(i, AutoLink)]
    assert autos[0].url == "http://github.com/eagredev"


def test_compile_bare_host_emits_annotation():
    out = inkmd.compile("Visit linkedin.com/in/dylan today.")
    assert b"/Subtype /Link" in out
    assert b"http://linkedin.com/in/dylan" in out


def test_bare_host_disabled_inside_link_text():
    """Inside [text](url), bare hosts stay as text."""
    inlines = _inlines("[my linkedin.com/in/dylan profile](https://other.com)")
    link = inlines[0]
    assert isinstance(link, Link)
    assert all(not isinstance(i, AutoLink) for i in link.inlines)
