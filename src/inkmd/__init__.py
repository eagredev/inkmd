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

from inkmd.html_filter import filter_document as filter_html
from inkmd.image_loader import resolve_images
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
    html: bool = True,
    base_dir: Path | None = None,
    allow_remote_images: bool = False,
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

    ``base_dir`` is the directory that relative image paths in markdown
    resolve against. When omitted (the default), relative paths resolve
    against the process's current working directory. ``render_file``
    sets ``base_dir`` to the directory of the source markdown file.

    ``allow_remote_images`` controls whether ``![alt](http://...)``
    image URLs are fetched at compile time. Off by default to preserve
    inkmd's zero-network promise; opt in for use cases (CI rendering
    of READMEs that pull in external badge images, etc.) that genuinely
    need it.
    """
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}; available: {tuple(FAMILIES)}")
    doc = parse(md_text, autolinks=autolinks, html=html)
    doc = filter_html(doc, html=html)
    doc = filter_document(doc, safe=safe)
    doc = resolve_images(doc, base_dir=base_dir, allow_remote=allow_remote_images)
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
    html: bool = True,
    allow_remote_images: bool = False,
) -> None:
    """Read markdown from ``in_path``; write PDF to ``out_path``.

    Relative image paths in the markdown resolve against the directory
    of ``in_path`` (not the process cwd).
    """
    src = Path(in_path)
    md = src.read_text(encoding="utf-8")
    Path(out_path).write_bytes(
        compile(
            md,
            page_size=page_size,
            family=family,
            autolinks=autolinks,
            safe=safe,
            html=html,
            base_dir=src.parent,
            allow_remote_images=allow_remote_images,
        )
    )
