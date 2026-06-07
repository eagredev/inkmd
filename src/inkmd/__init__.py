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

import unicodedata
from pathlib import Path

from inkmd.embedded import MissingGlyphWarning
from inkmd.html_filter import filter_document as filter_html
from inkmd.image_loader import resolve_images
from inkmd.parser import parse
from inkmd.pdf import styled_pdf
from inkmd.render import FAMILIES, render_document
from inkmd.url_filter import filter_document


__version__ = "0.4.0"

__all__ = ["compile", "render_file", "MissingGlyphWarning", "__version__"]


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
    emoji_fallback: str = "name",
    font_path: str | Path | None = None,
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
        emoji_fallback: What to do with an emoji the bundled color font
            can't render. The pip install bundles the font, so every emoji
            renders as a colour glyph and this setting has no visible
            effect there. It applies when emoji rendering is unavailable:
            under the ``INKMD_NO_EMOJI`` environment variable, or in the
            font-less single-file zipapp build. ``"name"`` (default)
            substitutes a short ``[rocket]``-style label so the meaning
            survives; ``"drop"`` omits the emoji entirely.
        font_path: Path to a TrueType (``glyf``-flavoured) font to embed
            for text the base-14 fonts can't represent (Cyrillic, Greek,
            Latin-Extended, ...). When None (default), inkmd embeds its
            bundled DejaVuSans. The font is embedded whole; non-WinAnsi
            text routes to it automatically while ASCII/Latin-1 stays on
            the base-14 family. A codepoint with no glyph in the chosen
            font (e.g. CJK under the bundled DejaVuSans) renders as a
            visible ``[U+XXXX]`` marker and inkmd raises one
            ``MissingGlyphWarning``, instead of a silent ``?``. A bad or
            unsupported font raises a clear ``TrueTypeFontError`` rather
            than a raw parse traceback.

    Returns:
        The compiled PDF as a ``bytes`` object. Byte-identical for the
        same input across platforms, Python versions, and repeated
        runs: no timestamps, no random identifiers, no platform-
        dependent iteration order.

    Raises:
        ValueError: If ``family`` is not one of the supported families,
            or ``emoji_fallback`` is not ``"name"`` or ``"drop"``.
        KeyError: If ``page_size`` is not one of the supported sizes.

    Example:
        >>> import inkmd
        >>> pdf = inkmd.compile("# Hello\\n\\nWorld.")
        >>> pdf[:4]
        b'%PDF'
    """
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}; available: {tuple(FAMILIES)}")
    # Normalize the whole markdown string to Unicode NFC at ingestion, before
    # any parsing. This is deliberate and whole-string: NFC is idempotent and
    # leaves ASCII untouched, so prose, URLs, structure, and code are all safe.
    # It composes decomposed sequences (e.g. NFD "café") to their single
    # codepoints (U+00E9) so the WinAnsi/embedded-font path renders them instead
    # of dropping the combining mark to "?". Code blocks are composed too, which
    # is intended (a code block holding a genuinely decomposed sequence for
    # display is vanishingly rare and out of S4 scope). NFC ONLY -- never NFKC,
    # which would rewrite ligatures/superscripts and change the author's
    # characters. Conformance harnesses call parse() directly, so this stays here
    # in compile() and leaves the spec-conformance surface byte-identical.
    md_text = unicodedata.normalize("NFC", md_text)
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
    # Scope the emoji text-fallback policy to this compile (ContextVar, so
    # the render functions need no extra threading and concurrent compiles
    # don't interfere).
    from inkmd.emoji import set_fallback_mode, reset_fallback_mode
    token = set_fallback_mode(emoji_fallback)
    try:
        paragraphs = render_document(
            doc, family=FAMILIES[family], content_width=content_width
        )
    finally:
        reset_fallback_mode(token)
    # Embedded-font wiring: if the document holds codepoints the base-14
    # WinAnsi path can't represent (Cyrillic/Greek/Latin-Ext), split those
    # runs onto an embedded font and emit it once. A pure-ASCII/Latin
    # document triggers none of this and stays byte-identical to pre-S5.
    from inkmd.embedded import (
        EmbeddedFontRef,
        document_uses_non_winansi,
        load_embedded_font,
        warn_missing_glyphs,
    )
    from inkmd.render import apply_embedding
    if document_uses_non_winansi(p.runs for p in paragraphs):
        loaded = load_embedded_font(font_path)
        # Collect every unrenderable codepoint (no base-14 byte AND no
        # embedded glyph) so it renders as a visible [U+XXXX] marker and we
        # raise ONE warning. ``ref`` is None in a font-less build, in which
        # case ALL non-WinAnsi text is unrenderable and gets the marker
        # instead of the old silent `?`.
        missing: list[int] = []
        ref = None
        if loaded is not None:
            font, font_bytes = loaded
            ref = EmbeddedFontRef(font=font, font_bytes=font_bytes)
        paragraphs = apply_embedding(paragraphs, ref, missing)
        warn_missing_glyphs(missing)
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
    emoji_fallback: str = "name",
    font_path: str | Path | None = None,
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
        emoji_fallback: ``"name"`` or ``"drop"`` for emoji the font can't
            render (zipapp / INKMD_NO_EMOJI only). See :func:`compile`.
        font_path: Override font to embed for non-WinAnsi text. See
            :func:`compile`.

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
            emoji_fallback=emoji_fallback,
            font_path=font_path,
        )
    )
