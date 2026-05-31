"""Image source resolution and format inspection for inkmd v0.2.

Resolves image URLs (local path, data: URI, optionally http(s)) into
raw bytes plus a small metadata header (format + pixel width/height).
The PDF emitter consumes the result and produces an /XObject; here we
only get as far as "bytes + dimensions + format".

Three sources:
  - Local filesystem path (relative or absolute)
  - data: URI (base64-encoded PNG or JPEG)
  - http:// or https:// URL — only when allow_remote=True

Two formats: PNG and JPEG. Both have well-defined dimension headers
that we parse without a third-party library.

Errors do not crash; the caller decides how to render the fallback
(typically alt text in italics). Every error path returns None.

The public entry point ``resolve_images`` walks a parsed Document
and returns a new Document with every Image node's ``resolved``
field populated (either an ``ImageData`` or None on failure). It
happens once, between parse and render, so the render layer stays
stateless about image loading.
"""

from __future__ import annotations

import base64
import io
import struct
import urllib.parse
from dataclasses import dataclass, replace
from pathlib import Path

from inkmd.ast import (
    AutoLink,
    BlockQuote,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    Heading,
    Image,
    Link,
    List,
    ListItem,
    Paragraph,
    Strikethrough,
    Strong,
    Table,
    TableCell,
    Text,
    ThematicBreak,
)


@dataclass(frozen=True)
class ImageData:
    """The bytes + dimensions of a successfully-loaded image."""
    format: str          # "png" or "jpeg"
    width: int           # pixels
    height: int          # pixels
    data: bytes          # raw bytes of the image file


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def resolve_images(
    doc: Document,
    *,
    base_dir: Path | None = None,
    allow_remote: bool = False,
) -> Document:
    """Walk ``doc`` and populate ``Image.resolved`` for every Image node.

    Returns a new Document tree; the input is not modified. Images whose
    URL is unreachable or whose format is unrecognised get
    ``resolved=None``, signalling to the renderer that the alt-text
    fallback should be used.

    Loaded image bytes are cached by URL within this call so repeated
    references to the same image don't re-read the file.
    """
    cache: dict[str, ImageData | None] = {}

    def get(url: str) -> ImageData | None:
        if url not in cache:
            cache[url] = load(url, base_dir=base_dir, allow_remote=allow_remote)
        return cache[url]

    return Document(blocks=tuple(_walk_block(b, get) for b in doc.blocks))


def _walk_block(block, get):
    if isinstance(block, Paragraph):
        return Paragraph(inlines=_walk_inlines(block.inlines, get))
    if isinstance(block, Heading):
        return Heading(level=block.level, inlines=_walk_inlines(block.inlines, get))
    if isinstance(block, BlockQuote):
        return _walk_blockquote_iterative(block, get)
    if isinstance(block, List):
        return List(
            ordered=block.ordered,
            start=block.start,
            tight=block.tight,
            items=tuple(
                ListItem(
                    blocks=tuple(_walk_block(b, get) for b in it.blocks),
                    task=it.task,
                )
                for it in block.items
            ),
        )
    if isinstance(block, Table):
        return Table(
            headers=tuple(
                TableCell(inlines=_walk_inlines(c.inlines, get)) for c in block.headers
            ),
            alignments=block.alignments,
            rows=tuple(
                tuple(TableCell(inlines=_walk_inlines(c.inlines, get)) for c in row)
                for row in block.rows
            ),
        )
    # CodeBlock, ThematicBreak — opaque.
    return block


def _walk_blockquote_iterative(root: BlockQuote, get) -> BlockQuote:
    """Walk a single-child blockquote chain iteratively.

    Same pattern as ``inkmd.url_filter._filter_blockquote_iterative``:
    descend a chain of nested BlockQuotes non-recursively so the
    resource-probe pathological case (10000-deep nesting) does not
    overflow Python's stack.
    """
    chain: list[BlockQuote] = []
    cur: BlockQuote | None = root
    while (
        isinstance(cur, BlockQuote)
        and len(cur.blocks) == 1
        and isinstance(cur.blocks[0], BlockQuote)
    ):
        chain.append(cur)
        cur = cur.blocks[0]
    if isinstance(cur, BlockQuote):
        leaf = BlockQuote(blocks=tuple(_walk_block(b, get) for b in cur.blocks))
    else:
        leaf = _walk_block(cur, get)  # type: ignore[arg-type]
    result = leaf
    for _ in chain:
        result = BlockQuote(blocks=(result,))
    return result


def _walk_inlines(inlines, get):
    out = []
    for node in inlines:
        if isinstance(node, Image):
            out.append(replace(
                node,
                inlines=_walk_inlines(node.inlines, get),
                resolved=get(node.url),
            ))
        elif isinstance(node, (Strong, Emphasis, Strikethrough)):
            new_inner = _walk_inlines(node.inlines, get)
            out.append(replace(node, inlines=new_inner))
        elif isinstance(node, Link):
            new_inner = _walk_inlines(node.inlines, get)
            out.append(replace(node, inlines=new_inner))
        else:
            out.append(node)
    return tuple(out)


def load(
    url: str,
    *,
    base_dir: Path | None = None,
    allow_remote: bool = False,
) -> ImageData | None:
    """Resolve and load an image source. Returns None on any failure.

    - Empty url -> None.
    - data: URI -> base64 decoded.
    - http(s) URL with allow_remote=True -> fetched (urllib, no auth).
    - http(s) URL with allow_remote=False -> None.
    - Otherwise treated as a filesystem path. Relative paths resolve
      against ``base_dir`` (the directory of the markdown source, when
      called from render_file) or cwd otherwise.
    """
    if not url:
        return None

    raw = _fetch_bytes(url, base_dir=base_dir, allow_remote=allow_remote)
    if raw is None:
        return None

    return _inspect(raw)


def _fetch_bytes(
    url: str,
    *,
    base_dir: Path | None,
    allow_remote: bool,
) -> bytes | None:
    """Return raw bytes for the URL or None on any failure."""
    # 1. data: URI
    if url.startswith("data:"):
        return _decode_data_uri(url)

    # 2. http(s) URL
    lower = url.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        if not allow_remote:
            return None
        return _fetch_http(url)

    # 3. Filesystem path. Strip any file:// prefix; reject obvious
    # path-traversal patterns? No — the markdown author has the same
    # filesystem authority the CLI already had.
    if url.startswith("file://"):
        url = url[len("file://"):]
    p = Path(url)
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    try:
        return p.read_bytes()
    except (OSError, ValueError):
        return None


def _decode_data_uri(uri: str) -> bytes | None:
    """Decode a ``data:[<mime>][;base64],<payload>`` URI."""
    # Strip "data:" prefix; find the first comma that separates meta from body.
    if not uri.startswith("data:"):
        return None
    comma = uri.find(",")
    if comma == -1:
        return None
    meta = uri[5:comma]
    body = uri[comma + 1:]
    # Meta is "[<mime>][;param][;base64]" — we only care whether ;base64
    # appears (vs. URL-encoded text).
    if ";base64" in meta:
        try:
            return base64.b64decode(body, validate=False)
        except (ValueError, base64.binascii.Error):
            return None
    # URL-decoded plain payload — not useful for an image but we honour
    # the spec shape.
    try:
        return urllib.parse.unquote_to_bytes(body)
    except Exception:  # noqa: BLE001
        return None


def _fetch_http(url: str) -> bytes | None:
    """Fetch a URL via urllib. Bounded by a small per-request timeout
    so we never hang a compile. Caller is responsible for caching."""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            return resp.read()
    except Exception:  # noqa: BLE001
        return None


def _inspect(raw: bytes) -> ImageData | None:
    """Identify the format and read dimensions from the raw bytes."""
    if raw.startswith(PNG_SIGNATURE):
        dims = _png_dimensions(raw)
        if dims is None:
            return None
        # Reject PNGs the emitter cannot turn into an XObject (no IDAT,
        # indexed-without-PLTE, interlaced, unsupported colour type). These
        # would otherwise pass dimension inspection and crash compile() at
        # emission time; instead they take the alt-text path like any other
        # unloadable image.
        if not _png_emittable(raw):
            return None
        return ImageData(format="png", width=dims[0], height=dims[1], data=raw)
    if raw.startswith(b"\xff\xd8"):
        dims = _jpeg_dimensions(raw)
        if dims is None:
            return None
        return ImageData(format="jpeg", width=dims[0], height=dims[1], data=raw)
    return None


# Colour types the PDF emitter supports: 0 (grey), 2 (RGB), 3 (indexed).
_SUPPORTED_PNG_COLOUR_TYPES = frozenset({0, 2, 3})


def _png_emittable(raw: bytes) -> bool:
    """True if a PNG (already past dimension inspection) carries everything
    the emitter needs to build an Image XObject.

    Mirrors the structural requirements of ``pdf._png_xobject_pieces``
    without importing it (the loader sits below the PDF layer): the PNG
    must be non-interlaced, a supported colour type, have at least one
    IDAT chunk, and — when indexed — have a PLTE palette. Any malformed
    or unsupported PNG returns False so it falls back to alt text rather
    than raising at emission.
    """
    # IHDR payload starts at signature(8)+len(4)+type(4) = byte 16.
    if len(raw) < 29:
        return False
    bit_depth = raw[24]
    colour_type = raw[25]
    interlace = raw[28]
    if interlace != 0:
        return False
    if colour_type not in _SUPPORTED_PNG_COLOUR_TYPES:
        return False
    if bit_depth == 0:
        return False
    # Walk chunks: need an IDAT, and a PLTE for indexed (type 3).
    offset = 8
    has_idat = False
    has_plte = False
    n = len(raw)
    while offset + 8 <= n:
        try:
            chunk_len = struct.unpack(">I", raw[offset:offset + 4])[0]
        except struct.error:
            return False
        chunk_type = raw[offset + 4:offset + 8]
        if chunk_type == b"IDAT":
            has_idat = True
        elif chunk_type == b"PLTE":
            has_plte = True
        elif chunk_type == b"IEND":
            break
        offset += 8 + chunk_len + 4
    if not has_idat:
        return False
    if colour_type == 3 and not has_plte:
        return False
    return True


def _png_dimensions(raw: bytes) -> tuple[int, int] | None:
    """Read width/height from a PNG.

    PNG layout: 8-byte signature, then chunks ``[len:4][type:4][data:len][crc:4]``.
    The first chunk is always IHDR which has width/height in its first
    8 bytes.
    """
    if len(raw) < 24:
        return None
    # IHDR chunk: 4 bytes length, 4 bytes "IHDR", then payload.
    if raw[12:16] != b"IHDR":
        return None
    try:
        w, h = struct.unpack(">II", raw[16:24])
    except struct.error:
        return None
    return w, h


def _jpeg_dimensions(raw: bytes) -> tuple[int, int] | None:
    """Read width/height from a JPEG by scanning for the SOF marker.

    Layout: a sequence of segments, each starting with 0xFF followed by
    a marker byte. SOFn markers (0xC0-0xC3, 0xC5-0xC7, 0xC9-0xCB, 0xCD-
    0xCF) carry the image dimensions in bytes 5-9 of their payload as
    (precision: u8, height: u16, width: u16).
    """
    stream = io.BytesIO(raw)
    # Skip SOI (0xFF 0xD8).
    if stream.read(2) != b"\xff\xd8":
        return None
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3,
        0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB,
        0xCD, 0xCE, 0xCF,
    }
    while True:
        b = stream.read(1)
        if not b:
            return None
        if b[0] != 0xFF:
            return None
        # Skip fill bytes (multiple 0xFF in a row).
        marker = stream.read(1)
        if not marker:
            return None
        while marker == b"\xff":
            marker = stream.read(1)
            if not marker:
                return None
        m = marker[0]
        # Standalone markers without payload: SOI (already past), EOI,
        # RSTn (0xD0-0xD7). Anything else has a 2-byte big-endian length.
        if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
            continue
        length_bytes = stream.read(2)
        if len(length_bytes) < 2:
            return None
        length = struct.unpack(">H", length_bytes)[0]
        if length < 2:
            return None
        if m in sof_markers:
            payload = stream.read(length - 2)
            if len(payload) < 5:
                return None
            h, w = struct.unpack(">HH", payload[1:5])
            return w, h
        # Skip this segment.
        stream.read(length - 2)
