"""Image support tests (v0.2 feature).

The image pipeline runs in three stages: parser (![alt](url) -> Image
AST node), resolver (load bytes + dimensions from disk / data: URI /
optional HTTP), and renderer (block-level images embed as PDF
XObjects; mixed-content images fall back to alt-text in italics;
unresolved images also fall back to alt text).

References:
    - CommonMark 0.31.2 section 6.4 (images)
    - src/inkmd/image_loader.py (loader + format inspector)
    - src/inkmd/pdf.py (_image_xobject_body, _png_xobject_pieces)
"""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import pytest

import inkmd
from inkmd.ast import AutoLink, Document, Image, Paragraph, Text
from inkmd.image_loader import ImageData, load, resolve_images
from inkmd.parser import parse


# --- Tiny test images built from scratch ---------------------------------


def _tiny_png(tmp_path: Path, name: str = "tiny.png", w: int = 2, h: int = 2) -> Path:
    """Build a tiny RGB PNG file and return its path."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    rows = b""
    for y in range(h):
        rows += b"\x00"  # filter byte
        for x in range(w):
            rows += bytes([
                max(0, min(255, 255 - 30 * x)),
                100,
                max(0, min(255, 50 + 30 * y)),
            ])
    idat = zlib.compress(rows)
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    p = tmp_path / name
    p.write_bytes(png)
    return p


def _tiny_jpeg_bytes() -> bytes:
    """Return a minimal 256x256 JPEG used as a fixture."""
    return bytes.fromhex(
        "FFD8FFE000104A46494600010100000100010000"
        "FFDB004300080606070605080707070909080A0C140D0C0B0B0C1912130F141D1A1F1E1D1A1C1C20242E2720222C231C1C2837292C30313434341F27393D38323C2E333432"
        "FFC0000B0801000100010111"
        "00"
        "FFC4001F0000010501010101010100000000000000000102030405060708090A0B"
        "FFC400B5100002010303020403050504040000017D01020300041105122131410613516107227114328191A1082342B1C11552D1F0243362728209"
        "0A161718191A25262728292A3435363738393A434445464748494A535455565758595A636465666768696A737475767778797A838485868788898A92"
        "939495969798999AA2A3A4A5A6A7A8A9AAB2B3B4B5B6B7B8B9BABACAB2C3C4C5C6C7C8C9CAD2D3D4D5D6D7D8D9DAE1E2E3E4E5E6E7E8E9EAF1F2F3F4F5F6F7F8F9FA"
        "FFDA0008010100003F00"
        "F8"
        "FFD9"
    )


def _tiny_jpeg(tmp_path: Path, name: str = "tiny.jpg") -> Path:
    p = tmp_path / name
    p.write_bytes(_tiny_jpeg_bytes())
    return p


# --- Parser ----------------------------------------------------------------


def test_parser_recognises_image_syntax():
    doc = parse("![alt text](image.png)")
    p = doc.blocks[0]
    assert isinstance(p, Paragraph)
    img = p.inlines[0]
    assert isinstance(img, Image)
    assert img.url == "image.png"
    assert img.inlines == (Text("alt text"),)


def test_parser_handles_title():
    doc = parse('![alt](image.png "Title here")')
    img = doc.blocks[0].inlines[0]
    assert img.title == "Title here"


def test_parser_image_with_formatted_alt():
    doc = parse("![**bold** and *italic*](image.png)")
    img = doc.blocks[0].inlines[0]
    assert any(not isinstance(n, Text) for n in img.inlines)


def test_parser_mixed_image_in_paragraph():
    doc = parse("Before ![alt](x.png) after.")
    inlines = doc.blocks[0].inlines
    assert isinstance(inlines[0], Text)
    assert isinstance(inlines[1], Image)
    assert isinstance(inlines[2], Text)


def test_bang_without_brackets_is_literal_text():
    doc = parse("Hello! World.")
    assert doc.blocks[0].inlines == (Text("Hello! World."),)


# --- Loader: PNG --------------------------------------------------------


def test_load_png_dimensions(tmp_path):
    p = _tiny_png(tmp_path, w=10, h=5)
    img = load(str(p))
    assert img is not None
    assert img.format == "png"
    assert img.width == 10
    assert img.height == 5


def test_load_jpeg_dimensions(tmp_path):
    p = _tiny_jpeg(tmp_path)
    img = load(str(p))
    assert img is not None
    assert img.format == "jpeg"
    assert img.width == 256
    assert img.height == 256


def test_load_missing_file_returns_none(tmp_path):
    img = load(str(tmp_path / "does-not-exist.png"))
    assert img is None


def test_load_non_image_file_returns_none(tmp_path):
    p = tmp_path / "not_an_image.txt"
    p.write_text("Hello, World!")
    img = load(str(p))
    assert img is None


def test_load_empty_url_returns_none():
    assert load("") is None


def test_load_data_uri_png(tmp_path):
    p = _tiny_png(tmp_path)
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    img = load(f"data:image/png;base64,{b64}")
    assert img is not None
    assert img.format == "png"


def test_load_remote_blocked_by_default():
    img = load("https://example.com/foo.png")
    assert img is None


def test_load_relative_path_uses_base_dir(tmp_path):
    p = _tiny_png(tmp_path)
    img = load(p.name, base_dir=tmp_path)
    assert img is not None
    assert img.format == "png"


# --- Resolver ---------------------------------------------------------------


def test_resolve_images_populates_resolved(tmp_path):
    p = _tiny_png(tmp_path)
    md = f"![alt]({p.name})"
    doc = parse(md)
    resolved = resolve_images(doc, base_dir=tmp_path)
    img = resolved.blocks[0].inlines[0]
    assert isinstance(img.resolved, ImageData)
    assert img.resolved.format == "png"


def test_resolve_images_caches_repeated_urls(tmp_path):
    p = _tiny_png(tmp_path)
    md = f"![a]({p.name})\n\n![b]({p.name})"
    doc = parse(md)
    resolved = resolve_images(doc, base_dir=tmp_path)
    img1 = resolved.blocks[0].inlines[0]
    img2 = resolved.blocks[1].inlines[0]
    assert img1.resolved is img2.resolved


def test_resolve_images_unreachable_leaves_resolved_none(tmp_path):
    doc = parse("![alt](/does/not/exist.png)")
    resolved = resolve_images(doc, base_dir=tmp_path)
    assert resolved.blocks[0].inlines[0].resolved is None


# --- End-to-end PDF rendering ---------------------------------------------


def test_compile_embeds_png_xobject(tmp_path):
    p = _tiny_png(tmp_path)
    md = f"![alt]({p})"
    pdf = inkmd.compile(md)
    assert b"/XObject" in pdf
    assert b"/Im0" in pdf
    assert b"/FlateDecode" in pdf
    assert b"/Predictor 15" in pdf


def test_compile_embeds_jpeg_with_dctdecode(tmp_path):
    p = _tiny_jpeg(tmp_path)
    md = f"![alt]({p})"
    pdf = inkmd.compile(md)
    assert b"/XObject" in pdf
    assert b"/DCTDecode" in pdf


def test_compile_missing_image_falls_back_to_alt_text(tmp_path):
    md = "![the missing image](/no/such/file.png)"
    pdf = inkmd.compile(md, base_dir=tmp_path)
    assert b"/F3" in pdf  # Helvetica-Oblique slot for italic alt
    assert b"/XObject" not in pdf


def test_compile_inline_image_uses_alt_fallback(tmp_path):
    p = _tiny_png(tmp_path)
    md = f"Before ![alt]({p}) after."
    pdf = inkmd.compile(md)
    assert b"/XObject" not in pdf


# --- Malformed PNG must fall back to alt text, never crash compile() ------
# Regression: a malformed-but-plausible PNG (valid IHDR, so it passes
# dimension inspection) used to crash compile() at emission time inside
# pdf._png_xobject_pieces instead of taking the alt-text path. Both cases
# below were confirmed HIGH-severity crashers in the 2026-05-30 audit.


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_indexed_no_idat() -> bytes:
    """Indexed PNG with IHDR + PLTE + IEND but NO IDAT chunk."""
    ihdr = struct.pack(">IIBBBBB", 2, 1, 8, 3, 0, 0, 0)
    return (
        _PNG_SIG
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"PLTE", b"\xff\x00\x00\x00\xff\x00")
        + _png_chunk(b"IEND", b"")
    )


def _png_indexed_no_plte() -> bytes:
    """Indexed PNG (colour type 3) with an IDAT but NO PLTE palette."""
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 3, 0, 0, 0)
    return (
        _PNG_SIG
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x00"))
        + _png_chunk(b"IEND", b"")
    )


def _data_uri(raw: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(raw).decode()


@pytest.mark.parametrize(
    "raw",
    [_png_indexed_no_idat(), _png_indexed_no_plte()],
    ids=["indexed-no-idat", "indexed-no-plte"],
)
def test_malformed_png_falls_back_to_alt_text_not_crash(raw):
    # The loader must reject it, so it never reaches the emitter.
    assert load(_data_uri(raw)) is None
    # compile() must succeed and render the alt text, not raise.
    md = f"![the alt text]({_data_uri(raw)})"
    pdf = inkmd.compile(md)
    assert pdf[:4] == b"%PDF"
    assert b"/XObject" not in pdf  # no image embedded
    assert b"/F3" in pdf  # Helvetica-Oblique slot used for italic alt text


def test_compile_same_image_referenced_twice_shares_xobject(tmp_path):
    p = _tiny_png(tmp_path)
    md = f"![a]({p})\n\n![b]({p})"
    pdf = inkmd.compile(md)
    assert b"/Im0" in pdf
    assert b"/Im1" not in pdf


def test_compile_remote_url_blocked_by_default(tmp_path):
    md = "![remote](https://example.com/image.png)"
    pdf = inkmd.compile(md, base_dir=tmp_path)
    assert b"/XObject" not in pdf


def test_compile_deterministic_for_image_documents(tmp_path):
    p = _tiny_png(tmp_path)
    md = f"![alt]({p})"
    pdf1 = inkmd.compile(md)
    pdf2 = inkmd.compile(md)
    assert pdf1 == pdf2


# --- HTML conformance serialiser -----------------------------------------


def test_html_serialiser_emits_img_tag():
    import sys
    sys.path.insert(0, "tests/conformance")
    from html_serialise import render_document

    doc = parse('![hello](img.png "the title")')
    html = render_document(doc)
    assert '<img src="img.png"' in html
    assert 'alt="hello"' in html
    assert 'title="the title"' in html


# --- Pagination after block-level images (red-team findings 0, 19, 43) -----


def _pages_for(md: str, base_dir: Path):
    """Compile md through the full pipeline and return layout Pages."""
    from inkmd.render import render_document, FAMILIES
    from inkmd.html_filter import filter_document as fh
    from inkmd.url_filter import filter_document as fu
    from inkmd.image_loader import resolve_images as ri
    from inkmd.layout import paginate_runs

    doc = parse(md)
    doc = fh(doc, html=True)
    doc = fu(doc, safe=True)
    doc = ri(doc, base_dir=base_dir, allow_remote=False)
    paras = render_document(doc, family=FAMILIES["helvetica"])
    return paginate_runs(paras, page_width=612, page_height=792)


def _lowest_y(pages) -> float:
    ys = [r.y for pg in pages for ln in pg.lines for r in ln.runs]
    ys += [getattr(s, "y", 999) for pg in pages for s in pg.shapes]
    return min(ys) if ys else 999.0


def test_second_tall_image_moves_to_fresh_page(tmp_path):
    """Regression: a block image that doesn't fit below a preceding image
    must move to a fresh page, not overflow the bottom margin / off-page."""
    _tiny_png(tmp_path, "a.png", w=80, h=400)
    _tiny_png(tmp_path, "b.png", w=80, h=350)
    pages = _pages_for("![a](a.png)\n\n![b](b.png)", tmp_path)
    assert len(pages) == 2
    # Nothing placed below the bottom margin (y=72) or off-page (y<0).
    assert _lowest_y(pages) >= 72 - 1e-6


def test_third_image_not_silently_lost_off_page(tmp_path):
    """Regression: three tall images must paginate to 3 pages; the third
    must not be pushed entirely off-page (silent content loss)."""
    _tiny_png(tmp_path, "a.png", w=80, h=400)
    _tiny_png(tmp_path, "b.png", w=80, h=350)
    _tiny_png(tmp_path, "c.png", w=80, h=350)
    pages = _pages_for("![a](a.png)\n\n![b](b.png)\n\n![c](c.png)", tmp_path)
    assert len(pages) == 3
    assert _lowest_y(pages) >= 72 - 1e-6


def test_thematic_break_after_tall_image_moves_to_fresh_page(tmp_path):
    """Regression: an HR that doesn't fit after a tall image moves to a
    fresh page instead of being drawn below the bottom margin."""
    _tiny_png(tmp_path, "a.png", w=80, h=640)
    pages = _pages_for("![a](a.png)\n\n---", tmp_path)
    assert len(pages) == 2
    assert _lowest_y(pages) >= 72 - 1e-6


def test_table_after_tall_image_moves_to_fresh_page(tmp_path):
    """Regression: a table that fits on its own page but not below a tall
    image must move to a fresh page, not overflow the bottom edge."""
    _tiny_png(tmp_path, "a.png", w=80, h=400)
    rows = "\n".join(f"| a{i} | b{i} |" for i in range(12))
    md = f"![a](a.png)\n\n| HA | HB |\n|---|---|\n{rows}"
    pages = _pages_for(md, tmp_path)
    assert len(pages) == 2
    assert _lowest_y(pages) >= 72 - 1e-6


# --- Indexed colour + tRNS transparency (Phase 1, emoji prerequisite) -----


def _indexed_png(
    tmp_path: Path,
    name: str = "idx.png",
    w: int = 4,
    h: int = 4,
    *,
    trns: bool = True,
) -> Path:
    """Build a tiny indexed (palette) PNG, optionally with a tRNS chunk.

    Palette: index 0 = red, 1 = green, 2 = blue. With tRNS, index 0 is
    fully transparent, 1 half, 2 opaque. Pixels cycle through the indices
    so every palette entry is exercised.
    """
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body))
        )
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)  # colour type 3 = indexed
    plte = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])  # red, green, blue
    rows = b""
    for y in range(h):
        rows += b"\x00"  # filter: None
        for x in range(w):
            rows += bytes([(x + y) % 3])
    idat = zlib.compress(rows)
    parts = [sig, chunk(b"IHDR", ihdr), chunk(b"PLTE", plte)]
    if trns:
        parts.append(chunk(b"tRNS", bytes([0, 128, 255])))
    parts += [chunk(b"IDAT", idat), chunk(b"IEND", b"")]
    p = tmp_path / name
    p.write_bytes(b"".join(parts))
    return p


def test_png_pieces_indexed_colorspace(tmp_path):
    from inkmd.image_loader import load as _load
    from inkmd.pdf import _png_xobject_pieces

    data = _load(str(_indexed_png(tmp_path, trns=False)))
    pieces = _png_xobject_pieces(data)
    assert pieces.colorspace.startswith("[/Indexed /DeviceRGB 2 <")
    assert pieces.components == 1
    assert pieces.alpha is None  # no tRNS -> opaque


def test_png_pieces_trns_builds_alpha_grid(tmp_path):
    from inkmd.image_loader import load as _load
    from inkmd.pdf import _png_xobject_pieces, _image_needs_smask

    data = _load(str(_indexed_png(tmp_path, w=3, h=3, trns=True)))
    assert _image_needs_smask(data)
    pieces = _png_xobject_pieces(data)
    assert pieces.alpha is not None
    assert len(pieces.alpha) == 3 * 3
    # The alpha grid must contain the three tRNS values (0,128,255 appear
    # because pixel indices cycle 0,1,2).
    assert set(pieces.alpha) == {0, 128, 255}


def test_indexed_png_without_trns_needs_no_smask(tmp_path):
    from inkmd.image_loader import load as _load
    from inkmd.pdf import _image_needs_smask

    data = _load(str(_indexed_png(tmp_path, trns=False)))
    assert not _image_needs_smask(data)


def test_compile_embeds_indexed_png_with_smask(tmp_path):
    """End-to-end: a transparent indexed PNG embeds as an /Indexed image
    plus a separate /SMask soft-mask object."""
    _indexed_png(tmp_path, "logo.png", w=8, h=8, trns=True)
    md = "![logo](logo.png)"
    pdf = inkmd.compile(md, base_dir=tmp_path)
    assert pdf[:4] == b"%PDF"
    assert b"/Indexed /DeviceRGB" in pdf
    assert b"/SMask" in pdf
    # The soft mask declares DeviceGray.
    assert b"/ColorSpace /DeviceGray" in pdf


def test_compile_indexed_png_deterministic(tmp_path):
    _indexed_png(tmp_path, "d.png", w=8, h=8, trns=True)
    md = "![d](d.png)"
    a = inkmd.compile(md, base_dir=tmp_path)
    b = inkmd.compile(md, base_dir=tmp_path)
    assert a == b


def test_unfilter_paeth_roundtrip():
    """The Paeth/Sub/Up/Average unfilter must reproduce known pixels.

    Build an indexed PNG whose rows use filter types and confirm the
    decoded alpha grid matches the source index pattern via tRNS lookup.
    """
    import struct as _s
    import zlib as _z
    from inkmd.image_loader import load as _load
    from inkmd.pdf import _png_xobject_pieces

    w = h = 4

    def chunk(tag, body):
        return _s.pack(">I", len(body)) + tag + body + _s.pack(">I", _z.crc32(tag + body))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _s.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
    plte = bytes([0, 0, 0, 255, 255, 255])  # 2 entries
    trns = bytes([0, 255])                   # idx0 transparent, idx1 opaque
    # Row pattern of indices, then apply Sub filter (type 1) to row 1,
    # Up (2) to row 2, Paeth (4) to row 3, None (0) to row 0.
    src = [[0, 1, 0, 1], [1, 1, 0, 0], [0, 0, 1, 1], [1, 0, 1, 0]]
    raw = b""
    prev = [0, 0, 0, 0]
    for y, row in enumerate(src):
        if y == 0:
            raw += b"\x00" + bytes(row)
        elif y == 1:  # Sub
            filt = [row[0]] + [(row[i] - row[i - 1]) & 0xFF for i in range(1, w)]
            raw += b"\x01" + bytes(filt)
        elif y == 2:  # Up
            filt = [(row[i] - prev[i]) & 0xFF for i in range(w)]
            raw += b"\x02" + bytes(filt)
        else:  # Paeth
            filt = []
            for i in range(w):
                a = row[i - 1] if i else 0
                b = prev[i]
                c = prev[i - 1] if i else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                filt.append((row[i] - pred) & 0xFF)
            raw += b"\x04" + bytes(filt)
        prev = row
    idat = _z.compress(raw)
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"PLTE", plte) + chunk(b"tRNS", trns) \
        + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    p = (Path(__file__).parent / "_paeth_tmp.png")
    p.write_bytes(png)
    try:
        data = _load(str(p))
        alpha = _png_xobject_pieces(data).alpha
        # Expected alpha = trns[index] for each source pixel.
        expected = bytes(trns[src[y][x]] for y in range(h) for x in range(w))
        assert alpha == expected
    finally:
        p.unlink()


# --- HTML <img> support (v0.2): promotion, width, alignment, security -----
# inkmd v0.2 promotes the HTML <img> tag to the same Image pipeline that
# markdown ![alt](url) uses, so the GitHub-README idiom
# <p align="center"><img src=... width=...></p> renders the image (and a
# caption, if present) instead of dropping it. <img> rides the existing
# resolve_images() base_dir / allow_remote gating — it is NOT a new
# security surface.


def test_html_img_embeds_like_markdown_image(tmp_path):
    p = _tiny_png(tmp_path)
    pdf = inkmd.compile(f'<img src="{p}" alt="a">')
    assert b"/XObject" in pdf
    assert b"/Im0" in pdf


def test_html_img_promotes_to_image_node():
    from inkmd.html_filter import filter_document as fh

    doc = fh(parse('<img src="x.png" alt="hi" width="640">'), html=True)
    img = next(n for n in doc.blocks[0].inlines if isinstance(n, Image))
    assert img.url == "x.png"
    assert img.display_width == 640.0
    assert "".join(t.content for t in img.inlines if isinstance(t, Text)) == "hi"


def test_html_img_without_src_falls_back_to_alt():
    from inkmd.html_filter import filter_document as fh

    doc = fh(parse('<img alt="just text">'), html=True)
    # No src → no Image node; the alt survives as plain text.
    assert not any(isinstance(n, Image) for n in doc.blocks[0].inlines)
    text = "".join(t.content for t in doc.blocks[0].inlines if isinstance(t, Text))
    assert "just text" in text


def test_html_img_width_capped_to_column(tmp_path):
    # A width larger than the text column is capped; aspect preserved.
    from inkmd.render import _render_image_block
    from inkmd.image_loader import resolve_images

    p = _tiny_png(tmp_path, w=10, h=5)
    doc = resolve_images(
        Document(blocks=(Paragraph(inlines=(
            Image(inlines=(), url=str(p), display_width=9999.0),
        )),)),
        base_dir=None,
    )
    img = doc.blocks[0].inlines[0]
    block = _render_image_block(img, content_width=468.0)
    shape = block.prepositioned_shapes[0]
    assert shape["width"] == 468.0                 # capped to column
    assert abs(shape["height"] - 468.0 * 0.5) < 1e-6  # 10x5 aspect kept


def test_html_img_center_alignment_offsets_x(tmp_path):
    from inkmd.render import _render_image_block
    from inkmd.image_loader import resolve_images

    p = _tiny_png(tmp_path, w=10, h=10)
    doc = resolve_images(
        Document(blocks=(Paragraph(inlines=(
            Image(inlines=(), url=str(p), display_width=200.0, align="center"),
        )),)),
        base_dir=None,
    )
    img = doc.blocks[0].inlines[0]
    block = _render_image_block(img, content_width=468.0)
    shape = block.prepositioned_shapes[0]
    assert shape["width"] == 200.0
    # Centered: x_offset = (column - width) / 2.
    assert abs(shape["x_offset"] - (468.0 - 200.0) / 2.0) < 1e-6


def test_p_align_center_propagates_to_child_img():
    from inkmd.html_filter import filter_document as fh

    hero = '<p align="center"><img src="h.png" alt="a" width="640"></p>'
    doc = fh(parse(hero), html=True)
    img = next(n for n in doc.blocks[0].inlines if isinstance(n, Image))
    assert img.align == "center"


def test_figure_with_caption_embeds_image_and_keeps_caption(tmp_path):
    # The hero idiom: <p align><img><br>caption</p> — image embeds as a
    # block, caption text survives.
    p = _tiny_png(tmp_path)
    md = f'<p align="center">\n<img src="{p}" alt="a" width="200">\n<br>\n<em>the caption</em>\n</p>'
    pdf = inkmd.compile(md)
    assert b"/XObject" in pdf          # image embedded
    # caption text is rendered (italic slot present + the word survives)
    from inkmd.pdf import encode_winansi
    assert encode_winansi("the caption") in pdf or b"caption" in pdf


def test_html_img_remote_blocked_by_default():
    # <img src="http..."> must obey the same allow_remote gate as markdown
    # images: not fetched unless explicitly opted in. Falls back to alt.
    md = '<img src="http://example.com/x.png" alt="remote pic">'
    pdf = inkmd.compile(md, allow_remote_images=False)
    assert b"/XObject" not in pdf
    assert pdf[:4] == b"%PDF"


def test_html_img_unresolved_falls_back_to_alt(tmp_path):
    md = '<img src="/no/such/img.png" alt="the missing pic">'
    pdf = inkmd.compile(md, base_dir=tmp_path)
    assert b"/XObject" not in pdf
    assert b"/F3" in pdf  # italic alt-text slot
