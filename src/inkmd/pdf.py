"""Minimum PDF emitter — milestone 0.0.1.

Produces a single-page PDF containing fixed text in Helvetica 12pt. No
markdown, no layout, no fonts beyond Helvetica. This module exists to
prove the bottom layer (byte-level PDF emission, xref construction,
deterministic output) works before anything else is built on top of it.

The educational comments will be trimmed once the team is comfortable
reading PDF bytes; for now they document the why of each piece.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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

    PDF string literals are delimited by parentheses, so the delimiters
    themselves and the escape char need backslash-escaping. Everything
    else passes through as-is in v0.1's ASCII-only world.
    """
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
