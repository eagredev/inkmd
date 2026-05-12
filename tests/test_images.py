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
