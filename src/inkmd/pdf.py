"""PDF emitter.

Milestone 0.0.1 introduced single-page emission (``hello_world_pdf``).
Milestone 0.0.2 adds multi-page emission (``text_pdf``) and a content-
stream builder for arbitrary positioned text runs.

The educational comments will be trimmed once the team is comfortable
reading PDF bytes; for now they document the why of each piece.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from inkmd.layout import (
    Page,
    PositionedRun,
    Run,
    StyledLine,
    paginate,
    paginate_runs,
    split_paragraphs,
)


# Font slot assignments for the styled path. F1 is regular body text
# so single-font PDFs (text_pdf) need no slot changes when emitting.
FONT_SLOTS: dict[str, str] = {
    "Helvetica": "F1",
    "Helvetica-Bold": "F2",
    "Helvetica-Oblique": "F3",
    "Courier": "F4",
}


# PDF uses points throughout. 1 inch = 72 points. A4 and Letter are the
# two page sizes we'll ship in v0.1.
PAGE_SIZES = {
    "A4": (595, 842),
    "letter": (612, 792),
}


@dataclass
class PDFWriter:
    """Stateful writer that accumulates PDF objects and emits the final bytes.

    PDFs require the xref table at the end to list every object's byte
    offset, which means we can't write straight to a stream — we have to
    buffer the body, record where each object lands, then build xref
    from the offsets we collected.
    """

    objects: list[bytes] = field(default_factory=list)

    def add_object(self, body: bytes) -> int:
        """Register an indirect object and return its object number (1-based).

        The body is the bytes between ``N 0 obj`` and ``endobj`` — not
        including those markers. The writer wraps them when serialising.
        """
        self.objects.append(body)
        return len(self.objects)

    def serialise(self, root_obj_num: int) -> bytes:
        """Emit the complete PDF byte sequence.

        Layout:
          1. ``%PDF-1.4`` header + four high-bit bytes (so file(1) and
             transfer tools treat it as binary, not text).
          2. Every object, in order, with ``N 0 obj`` / ``endobj`` wrappers.
             We record each object's start offset in ``xref_offsets``.
          3. The ``xref`` table: one row per object, listing byte offsets.
          4. The trailer dict (size + root reference) and ``startxref``
             pointing at where the xref table began.
          5. ``%%EOF``.
        """
        out = bytearray()
        # Header: PDF version + binary marker. The four >0x7f bytes are
        # an Adobe convention so tools auto-detect binary handling.
        out += b"%PDF-1.4\n"
        out += b"%\xe2\xe3\xcf\xd3\n"

        # Body: emit each object and remember its byte offset.
        xref_offsets: list[int] = []
        for idx, body in enumerate(self.objects, start=1):
            xref_offsets.append(len(out))
            out += f"{idx} 0 obj\n".encode("ascii")
            out += body
            if not body.endswith(b"\n"):
                out += b"\n"
            out += b"endobj\n"

        # xref table.
        xref_start = len(out)
        n_entries = len(self.objects) + 1  # +1 for the obligatory free-list head
        out += b"xref\n"
        out += f"0 {n_entries}\n".encode("ascii")
        # Entry 0 is the head of the free-object linked list. By
        # convention generation 65535 with object 0 marks "end of list".
        # Format of each entry: 10-digit offset, space, 5-digit generation,
        # space, single status char (f=free or n=in-use), CR LF (20 bytes).
        out += b"0000000000 65535 f \n"
        for offset in xref_offsets:
            out += f"{offset:010d} 00000 n \n".encode("ascii")

        # Trailer: tells the reader the total object count and which
        # object is the document root (catalog).
        out += b"trailer\n"
        out += f"<< /Size {n_entries} /Root {root_obj_num} 0 R >>\n".encode("ascii")
        out += b"startxref\n"
        out += f"{xref_start}\n".encode("ascii")
        out += b"%%EOF\n"

        return bytes(out)


def _content_stream(stream_body: bytes) -> bytes:
    """Wrap a content-stream body in a stream dict + stream/endstream.

    The /Length entry must precede /Filter and is computed from the body
    length. We don't apply Flate compression in v0.1 because raw streams
    are easier to debug and produce strictly deterministic output without
    needing to pin zlib versions.
    """
    return (
        f"<< /Length {len(stream_body)} >>\nstream\n".encode("ascii")
        + stream_body
        + b"\nendstream"
    )


def hello_world_pdf(text: str = "Hello, world!", page_size: str = "letter") -> bytes:
    """Emit a one-page PDF containing ``text`` in Helvetica 12pt at 1 inch margins.

    This is milestone 0.0.1: no markdown parsing, no layout, no font
    switching, no Unicode beyond ASCII. It exists to prove the byte
    pipeline works end-to-end.
    """
    width, height = PAGE_SIZES[page_size]
    writer = PDFWriter()

    # Object 1 — Catalog: the document root. Points at the pages tree.
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    writer.add_object(catalog)

    # Object 2 — Pages tree: lists all pages. We have one. The /Count
    # field is the number of leaf Page nodes under this subtree.
    pages = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    writer.add_object(pages)

    # Object 3 — Page: bounding box (MediaBox), resource dict pointing at
    # our font, and a reference to the content stream that draws on it.
    page = (
        f"<< /Type /Page /Parent 2 0 R "
        f"/MediaBox [0 0 {width} {height}] "
        f"/Resources << /Font << /F1 4 0 R >> >> "
        f"/Contents 5 0 R >>"
    ).encode("ascii")
    writer.add_object(page)

    # Object 4 — Font dict: declare Helvetica as the standard Type1 font
    # under the resource name /F1. The Type1 + BaseFont pair tells the
    # reader to use its built-in copy of Helvetica; we don't ship the
    # font file because it's one of the 14 spec-mandated base fonts.
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    writer.add_object(font)

    # Object 5 — Content stream: the drawing instructions for this page.
    #
    #   BT                begin text object
    #   /F1 12 Tf         use font /F1 at 12pt
    #   72 720 Td         move text cursor 1 inch from left, 1 inch from top
    #                     (PDF origin is bottom-left, so y = height - 72,
    #                      but for letter that's 792-72 = 720; we hardcode
    #                      for now and generalise in milestone 0.0.2)
    #   (text) Tj         show the literal string
    #   ET                end text object
    #
    # PDF string literals use parens; reserved chars (, ), and \ need
    # escaping. v0.1 is ASCII-only so we keep this simple.
    safe_text = _escape_pdf_string(text)
    y = height - 72  # 1 inch down from top, in PDF (bottom-origin) coords
    stream_body = (
        f"BT\n/F1 12 Tf\n72 {y} Td\n({safe_text}) Tj\nET".encode("ascii")
    )
    writer.add_object(_content_stream(stream_body))

    # Catalog is object 1; that's our document root.
    return writer.serialise(root_obj_num=1)


def _escape_pdf_string(s: str) -> str:
    """Escape (, ), and \\ inside a PDF literal string.

    Kept for hello_world_pdf and tests that work in pure ASCII. The
    multi-page emitters use ``_encode_pdf_literal`` which goes via the
    WinAnsi byte path.
    """
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _encode_pdf_literal(text: str) -> bytes:
    """Encode a string for direct insertion between parens in a content stream.

    Returns the byte sequence that goes between ``(`` and ``)``: the
    text WinAnsi-encoded with parens and backslashes escaped.
    """
    encoded = encode_winansi(text)
    return (
        encoded
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )


# WinAnsi remaps these typographic codepoints into the 0x80..0x9F range
# of single bytes. Without this, em dashes / curly quotes / ellipses
# would have no byte representation in v0.1's WinAnsi-only output.
_WINANSI_REMAP: dict[int, int] = {
    0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84,
    0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88,
    0x2030: 0x89, 0x0160: 0x8A, 0x2039: 0x8B, 0x0152: 0x8C,
    0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92, 0x201C: 0x93,
    0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
    0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B,
    0x0153: 0x9C, 0x017E: 0x9E, 0x0178: 0x9F,
}


def encode_winansi(text: str) -> bytes:
    """Encode a Python string into WinAnsi bytes for use inside a PDF literal.

    Codepoints 0x00..0xFF that exist in WinAnsi pass through directly.
    The remapped punctuation block (em/en dash, curly quotes, ellipsis,
    etc.) is translated into its WinAnsi byte. Anything else falls back
    to a ``?`` — v0.1 is a Latin-1 / WinAnsi-only product and we
    document that limitation; once TTF embedding lands in v0.2/0.3 the
    fallback path goes away.
    """
    out = bytearray()
    for ch in text:
        cp = ord(ch)
        if cp in _WINANSI_REMAP:
            out.append(_WINANSI_REMAP[cp])
        elif cp <= 0xFF:
            out.append(cp)
        else:
            out.append(ord("?"))
    return bytes(out)


def _page_content_stream(page: Page) -> bytes:
    """Build a content stream that draws every line in ``page``.

    Single-font path. Lines are drawn one at a time via absolute Tm
    positioning so future irregular spacing (headings, lists) drops in
    cleanly without offset accumulation.
    """
    parts = [b"BT"]
    current_font = None
    current_size = None
    for line in page.lines:
        if line.font != current_font or line.size != current_size:
            parts.append(f"/F1 {line.size} Tf".encode("ascii"))
            current_font = line.font
            current_size = line.size
        parts.append(f"1 0 0 1 {line.x} {line.y} Tm".encode("ascii"))
        parts.append(b"(" + _encode_pdf_literal(line.text) + b") Tj")
    parts.append(b"ET")
    return b"\n".join(parts)


def text_pdf(text: str, page_size: str = "letter") -> bytes:
    """Emit a (possibly multi-page) PDF from a plain-text input.

    Paragraphs are separated by blank lines; within a paragraph, line
    breaks are collapsed to spaces. Text is wrapped to fit within the
    column (page width minus 1-inch margins) and paginated. Helvetica
    12pt is the only font in milestone 0.0.2.
    """
    width, height = PAGE_SIZES[page_size]
    paragraphs = split_paragraphs(text)
    pages = paginate(paragraphs, page_width=width, page_height=height)

    # Edge case: input was all whitespace. Emit an empty page so the
    # output is still a valid PDF.
    if not pages:
        pages = [Page(lines=(), width=width, height=height)]

    writer = PDFWriter()

    # Reserve object slots for catalog, pages tree, and the font dict.
    # Pages and their content streams take the remaining numbers.
    # Numbering (5 fixed objects + 2 per page) keeps cross-refs simple.
    catalog_n = 1
    pages_tree_n = 2
    font_n = 3

    n_pages = len(pages)
    page_obj_nums = [4 + i * 2 for i in range(n_pages)]
    contents_obj_nums = [5 + i * 2 for i in range(n_pages)]

    # Catalog.
    writer.add_object(f"<< /Type /Catalog /Pages {pages_tree_n} 0 R >>".encode("ascii"))

    # Pages tree.
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    writer.add_object(
        f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("ascii")
    )

    # Font dict (shared by every page).
    writer.add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    # Per-page objects: Page + Contents stream, in lockstep.
    for page, page_n, contents_n in zip(pages, page_obj_nums, contents_obj_nums):
        page_obj = (
            f"<< /Type /Page /Parent {pages_tree_n} 0 R "
            f"/MediaBox [0 0 {page.width} {page.height}] "
            f"/Resources << /Font << /F1 {font_n} 0 R >> >> "
            f"/Contents {contents_n} 0 R >>"
        ).encode("ascii")
        writer.add_object(page_obj)

        stream_body = _page_content_stream(page) if page.lines else b"BT\nET"
        writer.add_object(_content_stream(stream_body))

    return writer.serialise(root_obj_num=catalog_n)


# --- Styled emission path (milestone 0.0.3) -------------------------------


def _styled_page_content_stream(page: Page) -> bytes:
    """Build a content stream for a page of ``StyledLine`` records.

    Each run is positioned absolutely via Tm; font switches emit a Tf
    only when font or size actually changes (cheaper output bytes).
    """
    parts = [b"BT"]
    current_font = None
    current_size = None
    for line in page.lines:
        for run in line.runs:
            if run.font != current_font or run.size != current_size:
                slot = FONT_SLOTS[run.font]
                parts.append(f"/{slot} {_fmt(run.size)} Tf".encode("ascii"))
                current_font = run.font
                current_size = run.size
            parts.append(
                f"1 0 0 1 {_fmt(run.x)} {_fmt(run.y)} Tm".encode("ascii")
            )
            parts.append(b"(" + _encode_pdf_literal(run.text) + b") Tj")
    parts.append(b"ET")
    return b"\n".join(parts)


def _fmt(n: float) -> str:
    """Format a float for PDF output: drop the trailing .0 on integers.

    PDF accepts both, but keeping integer coords as integers makes the
    byte output more compact and easier to read.
    """
    if n == int(n):
        return str(int(n))
    # Round to 3 decimal places — sub-millipoint precision is more than
    # any renderer cares about and keeps determinism trivial.
    return f"{n:.3f}".rstrip("0").rstrip(".")


def styled_pdf(
    paragraphs: list[list[Run]],
    page_size: str = "letter",
) -> bytes:
    """Emit a multi-page PDF from styled paragraph runs.

    Each paragraph is a list of ``Run`` objects. The four supported
    fonts (Helvetica, Helvetica-Bold, Helvetica-Oblique, Courier) are
    each declared as a font resource on every page.
    """
    width, height = PAGE_SIZES[page_size]
    pages = paginate_runs(paragraphs, page_width=width, page_height=height)

    if not pages:
        pages = [Page(lines=(), width=width, height=height)]

    writer = PDFWriter()

    catalog_n = 1
    pages_tree_n = 2
    # Four font objects, one per face. F1..F4 → object numbers 3..6.
    font_obj_nums: dict[str, int] = {}
    fixed_objects = 2  # catalog + pages tree, before fonts

    # Catalog.
    writer.add_object(f"<< /Type /Catalog /Pages {pages_tree_n} 0 R >>".encode("ascii"))

    n_pages = len(pages)
    n_fonts = len(FONT_SLOTS)
    page_obj_nums = [fixed_objects + n_fonts + 1 + i * 2 for i in range(n_pages)]
    contents_obj_nums = [fixed_objects + n_fonts + 2 + i * 2 for i in range(n_pages)]

    # Pages tree.
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    writer.add_object(
        f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("ascii")
    )

    # Font objects, in a deterministic order matching FONT_SLOTS.
    for font_name in FONT_SLOTS:
        obj_n = writer.add_object(
            (
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{font_name} >>"
            ).encode("ascii")
        )
        font_obj_nums[font_name] = obj_n

    # Resource dict: every font slot maps to its object.
    font_resource = " ".join(
        f"/{slot} {font_obj_nums[name]} 0 R"
        for name, slot in FONT_SLOTS.items()
    )

    for page, page_n, contents_n in zip(pages, page_obj_nums, contents_obj_nums):
        page_obj = (
            f"<< /Type /Page /Parent {pages_tree_n} 0 R "
            f"/MediaBox [0 0 {page.width} {page.height}] "
            f"/Resources << /Font << {font_resource} >> >> "
            f"/Contents {contents_n} 0 R >>"
        ).encode("ascii")
        writer.add_object(page_obj)

        stream_body = (
            _styled_page_content_stream(page) if page.lines else b"BT\nET"
        )
        writer.add_object(_content_stream(stream_body))

    return writer.serialise(root_obj_num=catalog_n)
