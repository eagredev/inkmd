"""inkmd — pure-Python markdown to PDF compiler.

Public API:

    inkmd.compile(md_text: str, page_size: str = "letter", family: str = "helvetica") -> bytes
        Parse markdown into PDF bytes.

    inkmd.render_file(in_path, out_path, page_size: str = "letter", family: str = "helvetica") -> None
        Read a markdown file, write a PDF file.

Font family choices: 'helvetica' (default, sans-serif) or 'times' (serif).
"""

from __future__ import annotations

from pathlib import Path

from inkmd.parser import parse
from inkmd.pdf import styled_pdf
from inkmd.render import FAMILIES, render_document
from inkmd.url_filter import filter_document


__version__ = "0.1.0"


def compile(
    md_text: str,
    page_size: str = "letter",
    family: str = "helvetica",
    *,
    autolinks: bool = True,
    safe: bool = True,
) -> bytes:
    """Compile markdown text into PDF bytes.

    ``autolinks`` controls GFM-style detection of bare URLs and email
    addresses (default True). Set False for strict CommonMark — bare
    URLs render as plain text and only `<url>` / `[text](url)` produce
    links.

    ``safe`` controls URL-scheme filtering on link annotations (default
    True). With ``safe=True``, only http(s), mailto, tel, ftp, and xmpp
    schemes pass through; anything else (javascript:, data:, vbscript:,
    file:, custom app schemes) renders as plain text with no clickable
    link. Set ``safe=False`` to disable the filter for trusted-content
    use cases.
    """
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}; available: {tuple(FAMILIES)}")
    doc = parse(md_text, autolinks=autolinks)
    doc = filter_document(doc, safe=safe)
    paragraphs = render_document(doc, family=FAMILIES[family])
    return styled_pdf(paragraphs, page_size=page_size)


def render_file(
    in_path: str | Path,
    out_path: str | Path,
    page_size: str = "letter",
    family: str = "helvetica",
    *,
    autolinks: bool = True,
    safe: bool = True,
) -> None:
    """Read markdown from ``in_path``; write PDF to ``out_path``."""
    md = Path(in_path).read_text(encoding="utf-8")
    Path(out_path).write_bytes(
        compile(
            md,
            page_size=page_size,
            family=family,
            autolinks=autolinks,
            safe=safe,
        )
    )
