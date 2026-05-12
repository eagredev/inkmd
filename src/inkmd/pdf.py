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
    ImagePlacement,
    Page,
    PositionedRun,
    Rect,
    Run,
    StyledLine,
    paginate,
    paginate_runs,
    split_paragraphs,
)


# Font slot assignments for the styled path. F1 is regular body text
# so single-font PDFs (text_pdf) need no slot changes when emitting.
# Eight faces declared per page: Helvetica family (regular/bold/oblique),
# Courier, and Times family (roman/bold/italic/bolditalic). The cost is
# tiny (~150 bytes of font dict per face × N pages) and lets demos and
# user code pick any face without re-emitting the structure.
FONT_SLOTS: dict[str, str] = {
    "Helvetica": "F1",
    "Helvetica-Bold": "F2",
    "Helvetica-Oblique": "F3",
    "Courier": "F4",
    "Times-Roman": "F5",
    "Times-Bold": "F6",
    "Times-Italic": "F7",
    "Times-BoldItalic": "F8",
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
    font = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
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


def _escape_literal_bytes(b: bytes) -> bytes:
    """Backslash-escape '(', ')', '\\' inside an already-encoded byte string."""
    return (
        b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    )


def _show_text_operator(text: str, font: str) -> bytes:
    """Return the content-stream bytes that draw ``text`` in ``font``.

    Emits ``(...) Tj`` for runs with no kerning pairs, or a TJ array
    with interleaved kerning offsets when pairs exist. The TJ array
    operator takes signed integers between strings where positive
    integers move the cursor *backward* by that many 1/1000 em — i.e.
    AFM's negative ``KPX`` adjustments become positive TJ numbers.
    """
    from inkmd.fonts import kerning_adjustment, to_winansi_byte

    if not text:
        return b"() Tj"

    # Walk through the text byte-by-byte, splitting on kerning pairs.
    # Each chunk is a run of bytes with no kerning between adjacent
    # bytes; kerning offsets sit between chunks.
    bytes_seq = [to_winansi_byte(ord(ch)) for ch in text]
    parts: list[tuple[bytes, int]] = []  # (chunk_bytes, kerning_after)
    chunk = bytearray([bytes_seq[0]])
    for i in range(1, len(bytes_seq)):
        adj = kerning_adjustment(font, bytes_seq[i - 1], bytes_seq[i])
        if adj != 0:
            # Close out the chunk before the kerning gap.
            parts.append((bytes(chunk), adj))
            chunk = bytearray([bytes_seq[i]])
        else:
            chunk.append(bytes_seq[i])
    parts.append((bytes(chunk), 0))

    # If only one chunk and no kerning, the simple Tj form is enough.
    if len(parts) == 1:
        return b"(" + _escape_literal_bytes(parts[0][0]) + b") Tj"

    # Otherwise emit a TJ array. Each chunk becomes a (string) literal;
    # between chunks we put the kerning offset (negated from AFM sign).
    array_parts: list[bytes] = []
    for i, (chunk_bytes, kern_after) in enumerate(parts):
        array_parts.append(b"(" + _escape_literal_bytes(chunk_bytes) + b")")
        if kern_after != 0 and i < len(parts) - 1:
            # AFM KPX -120 means "pull right glyph 120 units left", which in
            # TJ form is "+120 forward-by-negative" = +120 in array notation.
            array_parts.append(str(-kern_after).encode("ascii"))
    return b"[" + b" ".join(array_parts) + b"] TJ"


def encode_winansi(text: str) -> bytes:
    """Encode a Python string into WinAnsi bytes for use inside a PDF literal.

    Uses ``fonts.to_winansi_byte`` for the codepoint-to-byte mapping so
    measurement (in layout) and emission (here) agree on which glyph
    each character maps to. Latin-1 passes through, typographic
    punctuation remaps into 0x80..0x9F, anything else falls back to ?.
    """
    from inkmd.fonts import to_winansi_byte
    return bytes(to_winansi_byte(ord(ch)) for ch in text)


def _page_content_stream(page: Page) -> bytes:
    """Build a content stream that draws every line in ``page``.

    Single-font path. Lines are drawn one at a time via absolute Tm
    positioning. Kerning pairs are emitted as TJ arrays.
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
        parts.append(_show_text_operator(line.text, line.font))
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
    writer.add_object(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )

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


def _styled_page_content_stream(page: Page, image_xobject_names: dict[str, str] | None = None) -> bytes:
    """Build a content stream for a page of ``StyledLine`` records.

    Shapes (background rectangles, blockquote rules, images) are drawn
    first so text overlays them cleanly. Each text run is positioned
    absolutely via Tm; font switches emit a Tf only when font or size
    actually changes (cheaper output bytes).

    ``image_xobject_names`` maps an ImagePlacement.image_id to the
    /Im N resource slot name used in the page's /XObject dict. Required
    if the page contains any ImagePlacement shapes.
    """
    parts: list[bytes] = []
    image_xobject_names = image_xobject_names or {}
    # 1. Shapes — drawn before text. Filled rectangles use ``rg`` + ``re f``;
    #    images use ``q`` + ``cm`` + ``Do`` + ``Q`` (the q/Q wrap localises
    #    the cm transform so the next operator sees the identity matrix).
    current_rg: tuple[float, float, float] | None = None
    for shape in page.shapes:
        if isinstance(shape, ImagePlacement):
            slot = image_xobject_names.get(shape.image_id)
            if slot is None:
                # Should not happen — paginator + emitter agreed on the
                # resource table. Skip rather than crash if it does.
                continue
            parts.append(
                f"q {_fmt(shape.width)} 0 0 {_fmt(shape.height)} "
                f"{_fmt(shape.x)} {_fmt(shape.y)} cm /{slot} Do Q".encode("ascii")
            )
            continue
        if shape.fill != current_rg:
            r, g, b = shape.fill
            parts.append(f"{_fmt(r)} {_fmt(g)} {_fmt(b)} rg".encode("ascii"))
            current_rg = shape.fill
        parts.append(
            f"{_fmt(shape.x)} {_fmt(shape.y)} "
            f"{_fmt(shape.width)} {_fmt(shape.height)} re f".encode("ascii")
        )
    # Reset to black so text fill is correct (text inherits the current
    # nonstroking colour by default).
    if current_rg is not None:
        parts.append(b"0 0 0 rg")

    # 2. Text.
    parts.append(b"BT")
    current_font = None
    current_size = None
    current_text_rg: tuple[float, float, float] | None = None
    for line in page.lines:
        for run in line.runs:
            if run.font != current_font or run.size != current_size:
                slot = FONT_SLOTS[run.font]
                parts.append(f"/{slot} {_fmt(run.size)} Tf".encode("ascii"))
                current_font = run.font
                current_size = run.size
            run_color = getattr(run, "color", None)
            target_rg = run_color if run_color is not None else (0.0, 0.0, 0.0)
            if target_rg != current_text_rg:
                r, g, b = target_rg
                parts.append(f"{_fmt(r)} {_fmt(g)} {_fmt(b)} rg".encode("ascii"))
                current_text_rg = target_rg
            parts.append(
                f"1 0 0 1 {_fmt(run.x)} {_fmt(run.y)} Tm".encode("ascii")
            )
            parts.append(_show_text_operator(run.text, run.font))
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

    Each paragraph is a list of ``Run`` objects. The eight supported
    fonts (Helvetica family, Times family, Courier) are each declared
    as a font resource on every page.
    """
    width, height = PAGE_SIZES[page_size]
    pages = paginate_runs(paragraphs, page_width=width, page_height=height)

    if not pages:
        pages = [Page(lines=(), width=width, height=height)]

    # Collect every unique image referenced anywhere in the document,
    # in deterministic first-appearance order. Each gets a stable
    # /Im N resource slot and an XObject object number. Pages later
    # declare only the slots they actually use.
    image_order: list[str] = []
    image_data_by_id: dict[str, object] = {}
    page_image_ids: list[list[str]] = []
    for page in pages:
        used_on_page: list[str] = []
        for shape in page.shapes:
            if isinstance(shape, ImagePlacement):
                if shape.image_id not in image_data_by_id:
                    image_order.append(shape.image_id)
                    image_data_by_id[shape.image_id] = shape.image_data
                if shape.image_id not in used_on_page:
                    used_on_page.append(shape.image_id)
        page_image_ids.append(used_on_page)
    image_slot_by_id = {
        image_id: f"Im{idx}" for idx, image_id in enumerate(image_order)
    }

    writer = PDFWriter()

    catalog_n = 1
    pages_tree_n = 2

    # Pre-compute object numbers: catalog, pages tree, fonts, XObjects,
    # then per-page (page object, contents, annotations).
    fixed_objects = 2  # catalog + pages tree
    n_fonts = len(FONT_SLOTS)
    n_images = len(image_order)
    cursor = fixed_objects + n_fonts + n_images + 1

    n_pages = len(pages)
    page_obj_nums: list[int] = []
    contents_obj_nums: list[int] = []
    page_annot_obj_nums: list[list[int]] = []
    for page in pages:
        page_obj_nums.append(cursor); cursor += 1
        contents_obj_nums.append(cursor); cursor += 1
        annot_nums = []
        for _ann in getattr(page, "annotations", ()):
            annot_nums.append(cursor); cursor += 1
        page_annot_obj_nums.append(annot_nums)

    # Catalog.
    writer.add_object(f"<< /Type /Catalog /Pages {pages_tree_n} 0 R >>".encode("ascii"))

    # Pages tree.
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    writer.add_object(
        f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("ascii")
    )

    # Font objects.
    font_obj_nums: dict[str, int] = {}
    for font_name in FONT_SLOTS:
        obj_n = writer.add_object(
            (
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{font_name} "
                f"/Encoding /WinAnsiEncoding >>"
            ).encode("ascii")
        )
        font_obj_nums[font_name] = obj_n

    # Image XObjects.
    image_obj_nums: dict[str, int] = {}
    for image_id in image_order:
        data = image_data_by_id[image_id]
        body = _image_xobject_body(data)
        obj_n = writer.add_object(body)
        image_obj_nums[image_id] = obj_n

    # Resource fragments.
    font_resource = " ".join(
        f"/{slot} {font_obj_nums[name]} 0 R"
        for name, slot in FONT_SLOTS.items()
    )

    for page_idx, (page, page_n, contents_n, annot_nums) in enumerate(zip(
        pages, page_obj_nums, contents_obj_nums, page_annot_obj_nums
    )):
        annots_array = ""
        if annot_nums:
            refs = " ".join(f"{n} 0 R" for n in annot_nums)
            annots_array = f" /Annots [{refs}]"
        page_image_resource = ""
        if page_image_ids[page_idx]:
            entries = " ".join(
                f"/{image_slot_by_id[image_id]} {image_obj_nums[image_id]} 0 R"
                for image_id in page_image_ids[page_idx]
            )
            page_image_resource = f" /XObject << {entries} >>"
        page_obj = (
            f"<< /Type /Page /Parent {pages_tree_n} 0 R "
            f"/MediaBox [0 0 {page.width} {page.height}] "
            f"/Resources << /Font << {font_resource} >>{page_image_resource} >> "
            f"/Contents {contents_n} 0 R{annots_array} >>"
        ).encode("ascii")
        writer.add_object(page_obj)

        per_page_image_slots = {
            image_id: image_slot_by_id[image_id]
            for image_id in page_image_ids[page_idx]
        }
        stream_body = (
            _styled_page_content_stream(page, per_page_image_slots)
            if page.lines or page.shapes else b"BT\nET"
        )
        writer.add_object(_content_stream(stream_body))

        # Annotation objects for this page.
        for ann in getattr(page, "annotations", ()):
            writer.add_object(_link_annotation_object(ann))

    return writer.serialise(root_obj_num=catalog_n)


def _image_xobject_body(data) -> bytes:
    """Build the body of an Image XObject for a PNG or JPEG image.

    JPEG: the file body is passed through with /DCTDecode. PDF readers
    decode it natively.

    PNG: trickier. The PNG file's IDAT chunks contain row-filtered
    deflated data — *not* directly the raw pixel grid that PDF expects.
    We rely on PDF 1.5's /Predictor 15 flag which tells the reader to
    apply PNG row filtering after FlateDecode, so we can pass the IDAT
    bytes through verbatim (concatenated across chunks if there are
    several).
    """
    fmt = data.format
    width = data.width
    height = data.height
    if fmt == "jpeg":
        body = data.data
        dict_pairs = [
            "/Type /XObject",
            "/Subtype /Image",
            f"/Width {width}",
            f"/Height {height}",
            "/ColorSpace /DeviceRGB",
            "/BitsPerComponent 8",
            "/Filter /DCTDecode",
            f"/Length {len(body)}",
        ]
        header = "<< " + " ".join(dict_pairs) + " >>"
        return header.encode("ascii") + b"\nstream\n" + body + b"\nendstream"
    if fmt == "png":
        png_payload, colorspace, bpc, predictor_columns, png_colors = _png_xobject_pieces(data)
        dict_pairs = [
            "/Type /XObject",
            "/Subtype /Image",
            f"/Width {width}",
            f"/Height {height}",
            f"/ColorSpace {colorspace}",
            f"/BitsPerComponent {bpc}",
            "/Filter /FlateDecode",
            (
                "/DecodeParms << /Predictor 15 "
                f"/Colors {png_colors} /BitsPerComponent {bpc} "
                f"/Columns {predictor_columns} >>"
            ),
            f"/Length {len(png_payload)}",
        ]
        header = "<< " + " ".join(dict_pairs) + " >>"
        return header.encode("ascii") + b"\nstream\n" + png_payload + b"\nendstream"
    raise ValueError(f"unsupported image format: {fmt}")


def _png_xobject_pieces(data) -> tuple[bytes, str, int, int, int]:
    """Extract the IDAT byte stream + colour metadata from a PNG.

    Returns (idat_bytes, colorspace, bits_per_component, width,
    colour_components).
    """
    raw = data.data
    # IHDR is at bytes 8..33 (after 8-byte signature, 4 length, 4 "IHDR",
    # 13 data, 4 CRC). The 13 bytes of IHDR data:
    #   0..3   width
    #   4..7   height
    #   8      bit depth
    #   9      colour type
    #   10     compression method (0)
    #   11     filter method (0)
    #   12     interlace method (0 or 1)
    import struct
    ihdr = raw[16:29]
    bit_depth = ihdr[8]
    colour_type = ihdr[9]
    interlace = ihdr[12]
    if interlace != 0:
        raise ValueError("interlaced PNG not supported in v0.2")
    if colour_type == 0:
        colorspace = "/DeviceGray"
        components = 1
    elif colour_type == 2:
        colorspace = "/DeviceRGB"
        components = 3
    elif colour_type == 6:
        # RGBA. PDF /SMask handling is complex; for v0.2 we flatten alpha
        # onto a white background at decode time. Not ideal but enables
        # the typical "logo on a transparent background" case to render
        # without a runtime decode dependency.
        raise ValueError("RGBA PNG embedding pending v0.3")
    elif colour_type == 3:
        # Indexed colour: PDF needs the palette. Defer to v0.3.
        raise ValueError("indexed PNG pending v0.3")
    elif colour_type == 4:
        # Grayscale + alpha
        raise ValueError("grayscale+alpha PNG pending v0.3")
    else:
        raise ValueError(f"unknown PNG colour type {colour_type}")

    # Concatenate every IDAT chunk's data. PNG layout: signature(8) +
    # chunks(length(4) + type(4) + data(length) + crc(4)).
    offset = 8
    idat_parts: list[bytes] = []
    while offset < len(raw):
        chunk_len = struct.unpack(">I", raw[offset:offset + 4])[0]
        chunk_type = raw[offset + 4:offset + 8]
        chunk_data = raw[offset + 8:offset + 8 + chunk_len]
        if chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break
        offset += 8 + chunk_len + 4
    if not idat_parts:
        raise ValueError("PNG has no IDAT chunks")

    return b"".join(idat_parts), colorspace, bit_depth, data.width, components


def _link_annotation_object(ann) -> bytes:
    """Build the body of a /Link annotation PDF object.

    Format:
        << /Type /Annot /Subtype /Link
           /Rect [x1 y1 x2 y2]
           /Border [0 0 0]              -- invisible border (we draw our own underline)
           /A << /Type /Action /S /URI /URI (target) >> >>
    """
    x1 = _fmt(ann.x)
    y1 = _fmt(ann.y)
    x2 = _fmt(ann.x + ann.width)
    y2 = _fmt(ann.y + ann.height)
    uri_body = _encode_pdf_literal(ann.url)
    return (
        b"<< /Type /Annot /Subtype /Link "
        b"/Rect [" + f"{x1} {y1} {x2} {y2}".encode("ascii") + b"] "
        b"/Border [0 0 0] "
        b"/A << /Type /Action /S /URI /URI (" + uri_body + b") >> >>"
    )
