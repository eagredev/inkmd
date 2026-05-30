"""inkmd: pure-Python markdown to PDF compiler.

inkmd compiles markdown text into PDF bytes with zero runtime
dependencies and byte-deterministic output. Two public functions form
the entire API:

* :func:`compile` accepts markdown text and returns PDF bytes.
* :func:`render_file` reads a markdown file and writes a PDF file.

Both take the same keyword arguments. See each function's docstring
for the full list and defaults.

Typical use::

    import inkmd

    pdf_bytes = inkmd.compile("# Hello\\n\\nWorld.")

    inkmd.render_file("report.md", "report.pdf")

The library performs no network I/O, no subprocess execution, and no
template evaluation. The full security posture is documented in
``docs/security.md`` in the source repository.
"""

from __future__ import annotations

from pathlib import Path

from inkmd.html_filter import filter_document as filter_html
from inkmd.image_loader import resolve_images
from inkmd.parser import parse
from inkmd.pdf import styled_pdf
from inkmd.render import FAMILIES, render_document
from inkmd.url_filter import filter_document


__version__ = "0.2.0"

__all__ = ["compile", "render_file", "__version__"]


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

    Args:
        md_text: The markdown source to compile. UTF-8 text.
        page_size: Page size identifier. Accepts ``"letter"`` (8.5x11
            inches, default) or ``"A4"`` (210x297 mm).
        family: Font family for body text. Accepts ``"helvetica"``
            (sans-serif, default) or ``"times"`` (serif). Code blocks
            and inline code always render in Courier regardless.
        autolinks: When True (default), GFM-style bare URLs and email
            addresses are auto-linked (``https://example.com`` and
            ``user@example.com`` become clickable). Set False for
            strict CommonMark mode, where only ``<url>`` and
            ``[text](url)`` produce links.
        safe: When True (default), only the URL schemes ``http``,
            ``https``, ``mailto``, ``tel``, ``ftp``, and ``xmpp``
            produce clickable PDF link annotations. Other schemes
            (``javascript:``, ``data:``, ``vbscript:``, ``file:``,
            custom application schemes) render as plain text with
            the link annotation dropped. Set False to disable the
            filter for trusted-content use cases. The threat model
            is documented in ``docs/security.md``.
        html: When True (default), the curated inline HTML allow-list
            is active: tags such as ``<sub>``, ``<sup>``, ``<u>``,
            ``<mark>``, ``<kbd>``, ``<s>``, ``<del>``, and ``<br>``
            get typed PDF rendering; ``<span>``, ``<em>``, ``<strong>``
            unwrap to their content; ``<script>``, ``<style>``,
            ``<iframe>``, and similar tags are dropped with their
            content. Set False to render all HTML tags as literal
            text. The full allow-list and rationale are in
            ``docs/design/html-passthrough.md``.
        base_dir: Directory that relative image paths in markdown
            resolve against. When None (default), relative paths
            resolve against the process's current working directory.
            :func:`render_file` sets this to the parent directory of
            the source markdown file.
        allow_remote_images: When False (default), only local file
            paths and ``data:`` URIs are loaded for ``![alt](url)``
            image references; ``http(s)://`` URLs render with the
            alt-text fallback. Set True to fetch HTTP and HTTPS image
            URLs at compile time. Off by default to preserve inkmd's
            zero-network posture.

    Returns:
        The compiled PDF as a ``bytes`` object. Byte-identical for the
        same input across platforms, Python versions, and repeated
        runs: no timestamps, no random identifiers, no platform-
        dependent iteration order.

    Raises:
        ValueError: If ``family`` is not one of the supported families.
        KeyError: If ``page_size`` is not one of the supported sizes.

    Example:
        >>> import inkmd
        >>> pdf = inkmd.compile("# Hello\\n\\nWorld.")
        >>> pdf[:4]
        b'%PDF'
    """
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}; available: {tuple(FAMILIES)}")
    doc = parse(md_text, autolinks=autolinks, html=html)
    doc = filter_html(doc, html=html)
    doc = filter_document(doc, safe=safe)
    doc = resolve_images(doc, base_dir=base_dir, allow_remote=allow_remote_images)
    # Text-column width = page width minus both default 1in (72pt) margins.
    # Threaded into render so tables and block images are sized to the
    # actual page (A4 is narrower than letter and would otherwise overflow).
    from inkmd.pdf import PAGE_SIZES
    from inkmd.layout import DEFAULT_MARGIN
    page_w = PAGE_SIZES[page_size][0]
    content_width = page_w - 2 * DEFAULT_MARGIN
    paragraphs = render_document(doc, family=FAMILIES[family], content_width=content_width)
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
    """Read markdown from a file and write the compiled PDF to another file.

    Equivalent to reading ``in_path`` as UTF-8 text, calling
    :func:`compile` on the contents, and writing the resulting bytes to
    ``out_path``. Relative image paths in the markdown resolve against
    the directory of ``in_path`` (not the process's current working
    directory).

    Args:
        in_path: Path to the markdown source file. Read as UTF-8.
        out_path: Path the compiled PDF will be written to. Overwrites
            any existing file.
        page_size: Page size identifier. See :func:`compile`.
        family: Font family for body text. See :func:`compile`.
        autolinks: GFM bare-URL/email autolinking. See :func:`compile`.
        safe: URL-scheme filter for link annotations. See
            :func:`compile`.
        html: Inline HTML allow-list. See :func:`compile`.
        allow_remote_images: Allow fetching ``http(s)://`` image URLs
            at compile time. See :func:`compile`.

    Returns:
        None. The PDF is written to ``out_path`` as a side effect.

    Raises:
        ValueError: If ``family`` is not one of the supported families.
        KeyError: If ``page_size`` is not one of the supported sizes.
        OSError: If ``in_path`` cannot be read or ``out_path`` cannot
            be written.

    Example:
        >>> import inkmd
        >>> inkmd.render_file("report.md", "report.pdf")
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
