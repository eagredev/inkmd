"""PDF emitter.

Milestone 0.0.1 introduced single-page emission (``hello_world_pdf``).
Milestone 0.0.2 adds multi-page emission (``text_pdf``) and a content-
stream builder for arbitrary positioned text runs.

The educational comments will be trimmed once the team is comfortable
reading PDF bytes; for now they document the why of each piece.
"""

from __future__ import annotations

import zlib
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
# Nine faces declared per page: Helvetica family (regular/bold/oblique/
# bold-oblique), Courier, and Times family (roman/bold/italic/bolditalic).
# The cost is tiny (~150 bytes of font dict per face × N pages) and lets
# demos and user code pick any face without re-emitting the structure.
FONT_SLOTS: dict[str, str] = {
    "Helvetica": "F1",
    "Helvetica-Bold": "F2",
    "Helvetica-Oblique": "F3",
    "Courier": "F4",
    "Times-Roman": "F5",
    "Times-Bold": "F6",
    "Times-Italic": "F7",
    "Times-BoldItalic": "F8",
    "Helvetica-BoldOblique": "F9",
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
          1. ``%PDF-1.5`` header + four high-bit bytes (so file(1) and
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
        # PDF 1.5: the emitter uses /Predictor 15 (Flate predictor) and
        # /SMask soft masks, both of which are 1.5 features, so the header must
        # declare at least 1.5. Nothing here needs 1.6/1.7.
        out += b"%PDF-1.5\n"
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
    from inkmd.fonts import (
        is_zero_width_codepoint,
        kerning_adjustment,
        to_winansi_byte,
    )

    if not text:
        return b"() Tj"

    # Walk through the text byte-by-byte, splitting on kerning pairs.
    # Each chunk is a run of bytes with no kerning between adjacent
    # bytes; kerning offsets sit between chunks. Zero-width formatting
    # codepoints (soft hyphen) are dropped so they never print a glyph —
    # matching how text_width measures them (skipped).
    bytes_seq = [
        to_winansi_byte(ord(ch))
        for ch in text
        if not is_zero_width_codepoint(ord(ch))
    ]
    if not bytes_seq:
        return b"() Tj"
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
    from inkmd.fonts import is_zero_width_codepoint, to_winansi_byte
    return bytes(
        to_winansi_byte(ord(ch))
        for ch in text
        if not is_zero_width_codepoint(ord(ch))
    )


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
    # The current-font key is the (slot, size) pair actually selected: an
    # embedded run uses the /FEmb slot regardless of its base-14 ``font``
    # name, so two runs at the same size but different lanes still emit a Tf.
    current_font_key: tuple[str, float] | None = None
    current_text_rg: tuple[float, float, float] | None = None
    for line in page.lines:
        for run in line.runs:
            # Emoji runs are drawn as inline image XObjects (emitted into
            # the shapes section above), not as text glyphs — skip them
            # here so we don't stamp their placeholder text.
            if getattr(run, "emoji", None) is not None:
                continue
            embedded = getattr(run, "embedded", None)
            slot = "FEmb" if embedded is not None else FONT_SLOTS[run.font]
            font_key = (slot, run.size)
            if font_key != current_font_key:
                parts.append(f"/{slot} {_fmt(run.size)} Tf".encode("ascii"))
                current_font_key = font_key
            run_color = getattr(run, "color", None)
            target_rg = run_color if run_color is not None else (0.0, 0.0, 0.0)
            if target_rg != current_text_rg:
                r, g, b = target_rg
                parts.append(f"{_fmt(r)} {_fmt(g)} {_fmt(b)} rg".encode("ascii"))
                current_text_rg = target_rg
            run_y = run.y + getattr(run, "y_shift", 0.0)
            parts.append(
                f"1 0 0 1 {_fmt(run.x)} {_fmt(run_y)} Tm".encode("ascii")
            )
            if embedded is not None:
                # Identity-H CID hex (<HHHH...> Tj) over the embedded font's
                # native GIDs — see cidfont.show_text_cid_hex.
                from inkmd.cidfont import show_text_cid_hex
                parts.append(show_text_cid_hex(embedded.font, run.text))
            else:
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

    # Collect embedded-font usage across the whole document. All embedded
    # runs share ONE EmbeddedFontRef (one font object per document), so the
    # ref is taken from the first embedded run; the used codepoints are
    # gathered in DOCUMENT order (pages -> lines -> runs -> chars), deduped
    # while preserving first-appearance order, so emission never leaks a
    # set-iteration order. emit_embedded_font sorts GIDs internally, so the
    # set fed to it is order-independent regardless.
    embedded_ref = None
    embedded_codepoints: list[int] = []
    _seen_cps: set[int] = set()
    for page in pages:
        for line in page.lines:
            for run in line.runs:
                ref = getattr(run, "embedded", None)
                if ref is None:
                    continue
                if embedded_ref is None:
                    embedded_ref = ref
                for ch in run.text:
                    cp = ord(ch)
                    if cp not in _seen_cps:
                        _seen_cps.add(cp)
                        embedded_codepoints.append(cp)
    has_embedded = embedded_ref is not None

    writer = PDFWriter()

    catalog_n = 1
    pages_tree_n = 2

    # Pre-compute object numbers: catalog, pages tree, fonts, XObjects,
    # the embedded font's object graph, then per-page (page object,
    # contents, annotations).
    fixed_objects = 2  # catalog + pages tree
    n_fonts = len(FONT_SLOTS)
    n_images = len(image_order)
    # Transparent images (indexed PNG + tRNS) each need a second object for
    # their soft mask, so reserve those object numbers up front too.
    n_smasks = sum(
        1 for image_id in image_order
        if _image_needs_smask(image_data_by_id[image_id])
    )
    # The embedded font (Type0 + CIDFont + descriptor + FontFile2 +
    # ToUnicode) is 5 objects, added right after the image XObjects and
    # before the per-page objects, so the per-page numbering shifts cleanly.
    n_embedded = 5 if has_embedded else 0
    cursor = fixed_objects + n_fonts + n_images + n_smasks + n_embedded + 1

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

    # Image XObjects. A transparent image emits its soft-mask object
    # first (so the image dict can reference it by number), then the image
    # itself. The reserved-object count above accounts for both.
    image_obj_nums: dict[str, int] = {}
    for image_id in image_order:
        data = image_data_by_id[image_id]
        smask_n: int | None = None
        if _image_needs_smask(data):
            smask_n = writer.add_object(_smask_xobject_body(data))
        obj_n = writer.add_object(_image_xobject_body(data, smask_obj_num=smask_n))
        image_obj_nums[image_id] = obj_n

    # Embedded font object graph (one per document). emit_embedded_font adds
    # exactly the 5 objects reserved above (FontFile2, descriptor, ToUnicode,
    # CIDFont, Type0) and returns their numbers; the Type0 is the slot a page
    # references via /FEmb.
    embedded_type0_n: int | None = None
    if has_embedded:
        from inkmd.cidfont import emit_embedded_font
        objs = emit_embedded_font(
            writer,
            embedded_ref.font,
            embedded_ref.font_bytes,
            set(embedded_codepoints),
            base_font="InkmdEmbedded",
        )
        embedded_type0_n = objs.type0

    # Resource fragments.
    font_resource = " ".join(
        f"/{slot} {font_obj_nums[name]} 0 R"
        for name, slot in FONT_SLOTS.items()
    )
    if embedded_type0_n is not None:
        font_resource += f" /FEmb {embedded_type0_n} 0 R"

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


def _image_xobject_body(data, smask_obj_num: int | None = None) -> bytes:
    """Build the body of an Image XObject for a PNG or JPEG image.

    JPEG: the file body is passed through with /DCTDecode. PDF readers
    decode it natively.

    PNG: trickier. The PNG file's IDAT chunks contain row-filtered
    deflated data — *not* directly the raw pixel grid that PDF expects.
    We rely on PDF 1.5's /Predictor 15 flag which tells the reader to
    apply PNG row filtering after FlateDecode, so we can pass the IDAT
    bytes through verbatim (concatenated across chunks if there are
    several). Indexed (palette) PNGs use an /Indexed colour space built
    from the PLTE chunk; per-palette transparency (tRNS) becomes a
    separate /SMask image — see :func:`_image_needs_smask` and
    :func:`_smask_xobject_body`.

    ``smask_obj_num`` is the object number of the soft-mask XObject this
    image references via /SMask, or None if the image is fully opaque.
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
        pieces = _png_xobject_pieces(data)
        dict_pairs = [
            "/Type /XObject",
            "/Subtype /Image",
            f"/Width {width}",
            f"/Height {height}",
            f"/ColorSpace {pieces.colorspace}",
            f"/BitsPerComponent {pieces.bit_depth}",
            "/Filter /FlateDecode",
            (
                "/DecodeParms << /Predictor 15 "
                f"/Colors {pieces.components} /BitsPerComponent {pieces.bit_depth} "
                f"/Columns {width} >>"
            ),
        ]
        if smask_obj_num is not None:
            dict_pairs.append(f"/SMask {smask_obj_num} 0 R")
        dict_pairs.append(f"/Length {len(pieces.idat)}")
        header = "<< " + " ".join(dict_pairs) + " >>"
        return header.encode("ascii") + b"\nstream\n" + pieces.idat + b"\nendstream"
    raise ValueError(f"unsupported image format: {fmt}")


def _image_needs_smask(data) -> bool:
    """True if this image carries transparency that must be emitted as a
    separate /SMask XObject (indexed PNG with a tRNS chunk)."""
    if data.format != "png":
        return False
    return _png_xobject_pieces(data).alpha is not None


def _smask_xobject_body(data) -> bytes:
    """Build the soft-mask (/SMask) XObject body for a transparent PNG.

    The soft mask is an 8-bit DeviceGray image, one alpha byte per pixel
    (255 = opaque, 0 = fully transparent), Flate-compressed with no
    predictor. Only valid for images where :func:`_image_needs_smask`
    is True.
    """
    pieces = _png_xobject_pieces(data)
    if pieces.alpha is None:
        raise ValueError("image has no alpha channel for an SMask")
    # Pin the deflate level explicitly: zlib.compress with no level uses
    # Z_DEFAULT_COMPRESSION (-1), whose mapping is a property of the linked
    # zlib build, so the emitted SMask bytes could differ across platforms and
    # break the byte-determinism guarantee. Level 6 is the value standard zlib
    # maps the default to, so pinning it keeps output stable across builds
    # without changing the bytes on a standard zlib. (Deterministic per zlib
    # version, matching the 0.7 opt-in-compression decision.)
    payload = zlib.compress(pieces.alpha, level=6)
    dict_pairs = [
        "/Type /XObject",
        "/Subtype /Image",
        f"/Width {data.width}",
        f"/Height {data.height}",
        "/ColorSpace /DeviceGray",
        "/BitsPerComponent 8",
        "/Filter /FlateDecode",
        f"/Length {len(payload)}",
    ]
    header = "<< " + " ".join(dict_pairs) + " >>"
    return header.encode("ascii") + b"\nstream\n" + payload + b"\nendstream"


@dataclass(frozen=True)
class _PNGPieces:
    """Parsed PNG pieces needed to emit an Image XObject (+ optional SMask).

    ``idat`` is the verbatim row-filtered deflate stream (emitted with
    /Predictor 15). ``colorspace`` is the PDF colour-space token.
    ``components`` is the colour component count for the predictor (1 for
    gray/indexed, 3 for RGB). ``alpha``, when not None, is the raw 8-bit
    DeviceGray soft-mask pixel grid (width*height bytes) built from a
    palette tRNS chunk.
    """
    idat: bytes
    colorspace: str
    bit_depth: int
    components: int
    alpha: bytes | None


def _png_xobject_pieces(data) -> _PNGPieces:
    """Parse a PNG into the pieces needed to embed it as a PDF image.

    Supports greyscale (type 0), truecolour RGB (type 2), and indexed
    (type 3) PNGs. Indexed PNGs with a tRNS chunk additionally yield a
    soft-mask alpha grid. Interlaced, RGBA (type 6) and grey+alpha
    (type 4) PNGs are not yet supported.
    """
    import struct
    raw = data.data
    # IHDR data is the 13 bytes after signature(8)+len(4)+"IHDR"(4):
    #   0..3 width, 4..7 height, 8 bit depth, 9 colour type,
    #   10 compression, 11 filter, 12 interlace.
    ihdr = raw[16:29]
    bit_depth = ihdr[8]
    colour_type = ihdr[9]
    interlace = ihdr[12]
    if interlace != 0:
        raise ValueError("interlaced PNG not supported in v0.2")

    # Walk all chunks once, collecting IDAT + the palette / transparency
    # chunks indexed PNGs need. PNG layout: signature(8) + chunks
    # (length(4) + type(4) + data(length) + crc(4)).
    offset = 8
    idat_parts: list[bytes] = []
    palette: bytes | None = None
    trns: bytes | None = None
    while offset < len(raw):
        chunk_len = struct.unpack(">I", raw[offset:offset + 4])[0]
        chunk_type = raw[offset + 4:offset + 8]
        chunk_data = raw[offset + 8:offset + 8 + chunk_len]
        if chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"PLTE":
            palette = chunk_data
        elif chunk_type == b"tRNS":
            trns = chunk_data
        elif chunk_type == b"IEND":
            break
        offset += 8 + chunk_len + 4
    if not idat_parts:
        raise ValueError("PNG has no IDAT chunks")
    idat = b"".join(idat_parts)

    if colour_type == 0:
        return _PNGPieces(idat, "/DeviceGray", bit_depth, 1, None)
    if colour_type == 2:
        return _PNGPieces(idat, "/DeviceRGB", bit_depth, 3, None)
    if colour_type == 3:
        if palette is None:
            raise ValueError("indexed PNG missing PLTE palette")
        hival = len(palette) // 3 - 1
        palette_literal = "".join(f"{b:02X}" for b in palette)
        colorspace = f"[/Indexed /DeviceRGB {hival} <{palette_literal}>]"
        alpha = None
        if trns is not None:
            # tRNS for an indexed image is a list of per-palette-entry
            # alpha bytes (entries beyond its length are fully opaque).
            # Decode the indexed pixels and map each to its alpha to build
            # the soft mask.
            alpha = _indexed_alpha_grid(
                idat, data.width, data.height, bit_depth, trns
            )
        return _PNGPieces(idat, colorspace, bit_depth, 1, alpha)
    if colour_type == 6:
        raise ValueError("RGBA PNG embedding pending v0.3")
    if colour_type == 4:
        raise ValueError("grayscale+alpha PNG pending v0.3")
    raise ValueError(f"unknown PNG colour type {colour_type}")


def _indexed_alpha_grid(
    idat: bytes, width: int, height: int, bit_depth: int, trns: bytes
) -> bytes:
    """Decode an indexed PNG's pixels and map them to an 8-bit alpha grid.

    Returns ``width * height`` bytes, one alpha value per pixel in row
    order (255 where the palette entry is opaque or beyond the tRNS
    table). Inflates and PNG-unfilters the IDAT stream, then looks up each
    palette index in ``trns``.
    """
    raw = zlib.decompress(idat)
    # Indexed pixels are bit_depth bits each, packed MSB-first per row,
    # each row prefixed by one filter-type byte. Indexed colour uses only
    # filter 0 (None) and 1 (Sub) in practice; bpp for index data is 1.
    bytes_per_row = (width * bit_depth + 7) // 8
    stride = bytes_per_row + 1
    alpha = bytearray(width * height)
    prev_row = bytearray(bytes_per_row)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        row = bytearray(raw[pos + 1:pos + 1 + bytes_per_row])
        if ftype == 1:  # Sub: each byte += byte one pixel (1 byte) to the left
            for i in range(1, len(row)):
                row[i] = (row[i] + row[i - 1]) & 0xFF
        elif ftype == 2:  # Up: += byte above
            for i in range(len(row)):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(len(row)):
                left = row[i - 1] if i >= 1 else 0
                row[i] = (row[i] + ((left + prev_row[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(len(row)):
                a = row[i - 1] if i >= 1 else 0
                b = prev_row[i]
                c = prev_row[i - 1] if i >= 1 else 0
                row[i] = (row[i] + _paeth(a, b, c)) & 0xFF
        # ftype 0 (None): row unchanged.
        # Unpack indices from the row and map to alpha.
        for x in range(width):
            idx = _unpack_index(row, x, bit_depth)
            alpha[y * width + x] = trns[idx] if idx < len(trns) else 255
        prev_row = row
        pos += stride
    return bytes(alpha)


def _paeth(a: int, b: int, c: int) -> int:
    """PNG Paeth predictor: pick a, b or c by closest to a+b-c."""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unpack_index(row: bytearray, x: int, bit_depth: int) -> int:
    """Read the palette index of pixel ``x`` from a packed indexed row."""
    if bit_depth == 8:
        return row[x]
    # Sub-byte depths: MSB-first packing within each byte.
    per_byte = 8 // bit_depth
    byte = row[x // per_byte]
    shift = 8 - bit_depth * (x % per_byte + 1)
    return (byte >> shift) & ((1 << bit_depth) - 1)


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
