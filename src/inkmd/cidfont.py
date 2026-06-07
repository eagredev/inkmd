"""Type0 / CIDFontType2 PDF emission for an embedded TrueType font (Spine 3).

This is the *emission* layer of inkmd's font-embedding path. Given a
:class:`~inkmd.truetype.TrueTypeFont` and the set of Unicode codepoints a
document uses, it builds the PDF object graph that makes embedded (non-Latin)
text both RENDER and COPY/SEARCH correctly:

* a ``Type0`` composite font dict (``Identity-H`` encoding) whose descendant
  is a ``CIDFontType2``;
* the ``CIDFontType2`` dict with ``/CIDToGIDMap /Identity``, a ``/W`` width
  array, ``/DW`` default width, and an Adobe/Identity/0 ``/CIDSystemInfo``;
* a ``FontDescriptor`` carrying the embedded ``FontFile2``;
* the ``FontFile2`` stream: the raw font program, ``/Length1`` set to its
  uncompressed length, Flate-compressed at a pinned zlib level;
* a ``/ToUnicode`` CMap stream mapping each CID (== GID) back to its Unicode
  codepoint(s) so copy/paste and search work.

It also provides the content-stream show-text encoder: under ``Identity-H`` a
Type0 font shows glyphs as a string of **2-byte big-endian CIDs** (== GIDs),
``<...> Tj`` rather than the WinAnsi ``(...) Tj`` of the base-14 path.

DETERMINISM (the spine of this stream). The font is embedded WHOLE, with its
NATIVE glyph ids: Identity-H means ``CID == GID == the font's own glyph id``,
so there is NO per-document glyph renumbering and NO subsetting. Consequences
honored here:

* ``/CIDToGIDMap /Identity`` (CID *n* is GID *n*) — never a remapped table.
* ``/W`` and ``/ToUnicode`` are emitted over GIDs in **ascending GID order**.
  The used-codepoint set is mapped to GIDs and then SORTED before any
  iteration, so output never depends on a ``set``/``dict`` iteration order
  that could vary across runs or Python versions. (Order-independence is
  asserted in the tests: two input orders -> identical bytes.)
* ``FontFile2`` is the unmodified font program, a pure function of the input
  font, not of which codepoints the document used.
* Flate uses a PINNED level (``zlib.compress(data, level=6)``), matching the
  S0a SMask fix. Level 6 is what standard zlib maps its default to, so this
  is deterministic per zlib version (the accepted trade, stated openly).
* No float ever reaches the emitted bytes: widths, ``/DW`` and the descriptor
  metrics are integers; any computation rounds to ``int`` before formatting.

This module emits no document on its own and is UNUSED by the live
``styled_pdf`` path: run-routing / font selection (which run uses the embedded
font) is Spine 5. ``pdf.py``'s base-14 WinAnsi path is untouched. The object
NUMBERS are supplied by the caller (an :class:`~inkmd.pdf.PDFWriter`), so these
functions are pure ``(font, codepoints, obj-numbers) -> bytes`` builders.

Pure stdlib only (``struct`` via S1, ``zlib``). No new dependency, no bundled
font asset.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from inkmd.truetype import TrueTypeFont, TrueTypeFontError

# Pinned Flate level for FontFile2. See the module docstring: level 6 is the
# standard-zlib default mapping, deterministic per zlib version. Matches the
# S0a SMask fix and the 0.7 compression decision. NEVER call zlib.compress
# with no level here.
_FLATE_LEVEL = 6

# A defensible default for /StemV. The real value lives in the (private) hint
# program, which S1 does not parse; viewers use StemV only as a synthesis hint
# when the embedded outline is unavailable, which never happens here because
# the full FontFile2 is embedded. 80 is the conventional fallback (a normal
# upright stem weight). NAMED as a constant in the worker report.
_DEFAULT_STEM_V = 80

# Nonsymbolic flag (bit 6, value 32) in the FontDescriptor /Flags. We set
# Nonsymbolic for text fonts mapped through a real cmap; this is a coherent
# constant, NAMED as such in the report. (Symbolic/Nonsymbolic are mutually
# exclusive; a fully correct value would inspect OS/2 + the cmap platform, out
# of S1's parsed surface.)
_FLAG_NONSYMBOLIC = 1 << 5


def used_gids(font: TrueTypeFont, codepoints: set[int]) -> list[int]:
    """Map ``codepoints`` to glyph ids and return them SORTED + deduped.

    This is the determinism gate for ``/W`` and ``/ToUnicode``: callers pass a
    ``set`` (order-undefined), and every consumer iterates the SORTED result,
    so emitted bytes never depend on input iteration order. Codepoints absent
    from the font's ``cmap`` map to GID 0 (.notdef) and are included only if
    GID 0 is genuinely produced. GID 0 itself is always implicitly present in
    the font but only appears here if some codepoint resolved to it.
    """
    gids = {font.glyph_id(cp) for cp in codepoints}
    return sorted(gids)


def gid_to_codepoints(
    font: TrueTypeFont, codepoints: set[int]
) -> dict[int, list[int]]:
    """Build a GID -> sorted list of codepoints map for the ToUnicode CMap.

    A single GID can be reached from several codepoints (e.g. a font that maps
    both U+00B5 MICRO SIGN and U+03BC GREEK SMALL MU to one glyph). ToUnicode
    must pick ONE destination per GID (it is a glyph->text map), so we choose
    the smallest codepoint deterministically. The full sorted list is returned
    so callers/tests can see every contributing codepoint; emission uses the
    first (smallest).
    """
    mapping: dict[int, list[int]] = {}
    for cp in codepoints:
        gid = font.glyph_id(cp)
        mapping.setdefault(gid, []).append(cp)
    for gid in mapping:
        mapping[gid] = sorted(mapping[gid])
    return mapping


# --- FontDescriptor metric extraction -------------------------------------


@dataclass(frozen=True)
class _DescriptorMetrics:
    """Integer FontDescriptor metrics, font-derived where S1's tables allow.

    Every field is an ``int`` (no float reaches emitted bytes). ``stem_v`` and
    ``flags`` are constants (see module constants); the rest are read from
    ``head``/``hhea``/``OS/2`` when present, with stated fallbacks.
    """

    bbox: tuple[int, int, int, int]
    ascent: int
    descent: int
    cap_height: int
    flags: int
    stem_v: int


def _read_descriptor_metrics(font: TrueTypeFont) -> _DescriptorMetrics:
    """Extract FontDescriptor metrics from the font's own tables.

    FontBBox comes from ``head`` (xMin/yMin/xMax/yMax @ +36..+44). Ascent and
    Descent come from ``hhea`` (ascender @ +4, descender @ +6) — real
    font-derived values. CapHeight is read from ``OS/2`` v2+ (sCapHeight @
    +88) when the table is long enough; otherwise it falls back to the ascent
    (NAMED as a fallback in the report). All values are signed int16 in design
    units, returned as ``int``. StemV and Flags are constants.
    """
    data = font._data  # raw font bytes; S1 owns parsing, we read 2 more fields

    # FontBBox from head (already bounds-checked enough that units_per_em read
    # succeeds; re-validate the bbox span).
    font.units_per_em  # force head parse / validation
    head_off, head_len = font.tables["head"]
    if head_len < 46 or head_off + 46 > len(data):
        raise TrueTypeFontError("truncated head table for FontBBox")
    x_min, y_min, x_max, y_max = struct.unpack(
        ">hhhh", data[head_off + 36 : head_off + 44]
    )

    # Ascent / Descent from hhea.
    hhea_off, hhea_len = font.tables["hhea"]
    if hhea_len < 8 or hhea_off + 8 > len(data):
        raise TrueTypeFontError("truncated hhea table for ascent/descent")
    ascender, descender = struct.unpack(">hh", data[hhea_off + 4 : hhea_off + 8])

    # CapHeight from OS/2 v2+ if available, else fall back to ascender.
    cap_height = ascender  # fallback, NAMED in report
    os2 = font.tables.get("OS/2")
    if os2 is not None:
        os2_off, os2_len = os2
        # sCapHeight is at +88 in OS/2 version >= 2.
        if os2_len >= 90 and os2_off + 90 <= len(data):
            version = struct.unpack(">H", data[os2_off : os2_off + 2])[0]
            if version >= 2:
                cap_height = struct.unpack(
                    ">h", data[os2_off + 88 : os2_off + 90]
                )[0]

    return _DescriptorMetrics(
        bbox=(int(x_min), int(y_min), int(x_max), int(y_max)),
        ascent=int(ascender),
        descent=int(descender),
        cap_height=int(cap_height),
        flags=_FLAG_NONSYMBOLIC,
        stem_v=_DEFAULT_STEM_V,
    )


# --- /W width array -------------------------------------------------------


def _pdf_glyph_width(font: TrueTypeFont, gid: int) -> int:
    """Glyph ``gid``'s advance in PDF glyph space (1/1000 em), as int.

    Per the PDF spec, the Type0 ``/W`` width array and ``/DW`` default width
    are ALWAYS in units of 1/1000 of text space (a fixed 1000-unit em),
    *regardless* of the font program's internal ``unitsPerEm``. (Glyph
    *outlines* self-scale via the font program's own ``unitsPerEm`` — PDF
    handles that automatically for CIDFontType2 — but the width arrays do not;
    they use the fixed 1000 convention.) So a raw design-unit advance must be
    rescaled: a DejaVuSans glyph (em 2048) with raw advance 1995 emits as
    ``round(1995 * 1000 / 2048) = 974``; a 1000-em font is unaffected (scale
    factor 1).

    Determinism: ``round(advance * 1000 / units_per_em)`` forms an exact
    integer numerator, does a SINGLE IEEE-754 division, then applies Python's
    round-half-to-even. That is deterministic across CPython 3.9-3.13. The
    result is an ``int``; no float reaches the emitted bytes. Do NOT scale the
    FontDescriptor metrics (FontBBox/Ascent/Descent/CapHeight) — those are
    correctly in design units for a FontDescriptor. ONLY ``/W``/``/DW`` use the
    1000-em convention.
    """
    return round(font.advance_width(gid) * 1000 / font.units_per_em)


def _width_array(font: TrueTypeFont, gids: list[int]) -> str:
    """Build the ``/W`` array body for ``gids`` (SORTED ascending).

    Format: a sequence of ``CID [w0 w1 ...]`` runs, one run per maximal block
    of consecutive GIDs, so e.g. GIDs 5,6,7 emit ``5 [w5 w6 w7]``. Widths are
    integer PDF glyph-space (1/1000 em) advances — see :func:`_pdf_glyph_width`
    for the 1000-em scaling. Iterating the pre-sorted ``gids`` keeps output
    order-independent. Returns the inside of the ``[ ... ]`` (without the
    surrounding brackets).
    """
    if not gids:
        return ""
    runs: list[str] = []
    i = 0
    n = len(gids)
    while i < n:
        start = gids[i]
        widths = [_pdf_glyph_width(font, gids[i])]
        j = i + 1
        while j < n and gids[j] == gids[j - 1] + 1:
            widths.append(_pdf_glyph_width(font, gids[j]))
            j += 1
        widths_str = " ".join(str(int(w)) for w in widths)
        runs.append(f"{start} [{widths_str}]")
        i = j
    return " ".join(runs)


def default_width(font: TrueTypeFont) -> int:
    """Return the ``/DW`` default width: GID 0's (.notdef) advance, as int.

    Any GID not covered by ``/W`` inherits this. Using .notdef's real advance
    means a glyph the document never used still has a defensible box width.
    The value is in PDF glyph space (1/1000 em), NOT the font's design units —
    see :func:`_pdf_glyph_width`.
    """
    return _pdf_glyph_width(font, 0)


# --- Show-text (Identity-H CID hex) ---------------------------------------


def show_text_cid_hex(font: TrueTypeFont, text: str) -> bytes:
    """Encode ``text`` as an Identity-H ``<hex> Tj`` show-text operator.

    Each character is mapped through ``font.glyph_id`` to its native GID, and
    each GID is packed as a 2-byte BIG-ENDIAN value (Identity-H, CID == GID).
    The result is ``<HHHH...> Tj`` with uppercase hex, e.g. a single GID 0x48
    yields ``<0048> Tj``. An empty string yields ``<> Tj``.

    GIDs above 0xFFFF cannot be represented in 2 bytes; v0.4 embeds the native
    GID space and a real text font's used glyphs sit well below 0x10000, so a
    GID >= 0x10000 raises rather than silently truncating.

    This stays a dumb encoder: by the time text reaches here the S6 run-split
    (``split_run_for_embedding``) has already routed any glyphless codepoint
    onto the base-14 ``[U+XXXX]`` marker, so a SPLIT document's embedded runs
    should hold only real glyphs - gid 0 (.notdef) should no longer occur
    here for split text. The marker fix lives in the split, NOT this encoder.
    """
    out = bytearray()
    for ch in text:
        gid = font.glyph_id(ord(ch))
        if gid > 0xFFFF:
            raise TrueTypeFontError(
                f"glyph id {gid} exceeds 2-byte Identity-H CID range"
            )
        out += struct.pack(">H", gid)
    return b"<" + out.hex().upper().encode("ascii") + b"> Tj"


# --- Object-body builders -------------------------------------------------
#
# Each returns the bytes between "N 0 obj" and "endobj" for one PDF object.
# Cross-reference object numbers are supplied by the caller (PDFWriter), so
# nothing here assumes a numbering scheme or touches the live path.


def type0_font_object(
    base_font: str, descendant_obj_num: int, tounicode_obj_num: int
) -> bytes:
    """Body of the Type0 font dict (the resource a page's /Font slot points at).

    ``Identity-H`` encoding, one descendant CIDFont, a ToUnicode ref.
    """
    return (
        f"<< /Type /Font /Subtype /Type0 /BaseFont /{base_font} "
        f"/Encoding /Identity-H "
        f"/DescendantFonts [{descendant_obj_num} 0 R] "
        f"/ToUnicode {tounicode_obj_num} 0 R >>"
    ).encode("ascii")


def cidfont_object(
    font: TrueTypeFont,
    base_font: str,
    gids: list[int],
    descriptor_obj_num: int,
) -> bytes:
    """Body of the CIDFontType2 descendant dict.

    ``/CIDToGIDMap /Identity`` (CID == GID), Adobe/Identity/0 CIDSystemInfo, a
    ``/W`` array over the SORTED ``gids`` and a ``/DW`` default width. Widths
    are integer PDF glyph-space (1/1000 em) advances (see
    :func:`_pdf_glyph_width`), NOT the font's raw design units.
    """
    dw = default_width(font)
    w_body = _width_array(font, gids)
    return (
        f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{base_font} "
        f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
        f"/Supplement 0 >> "
        f"/FontDescriptor {descriptor_obj_num} 0 R "
        f"/CIDToGIDMap /Identity "
        f"/DW {dw} /W [{w_body}] >>"
    ).encode("ascii")


def font_descriptor_object(
    font: TrueTypeFont, base_font: str, fontfile_obj_num: int
) -> bytes:
    """Body of the FontDescriptor.

    FontBBox/Ascent/Descent/CapHeight are font-derived (see
    :func:`_read_descriptor_metrics`); Flags and StemV are NAMED constants.
    References the embedded ``/FontFile2``.
    """
    m = _read_descriptor_metrics(font)
    x0, y0, x1, y1 = m.bbox
    return (
        f"<< /Type /FontDescriptor /FontName /{base_font} "
        f"/Flags {m.flags} "
        f"/FontBBox [{x0} {y0} {x1} {y1}] "
        f"/ItalicAngle 0 "
        f"/Ascent {m.ascent} /Descent {m.descent} /CapHeight {m.cap_height} "
        f"/StemV {m.stem_v} "
        f"/FontFile2 {fontfile_obj_num} 0 R >>"
    ).encode("ascii")


def fontfile2_stream_object(font_bytes: bytes) -> bytes:
    """Body of the FontFile2 stream: the FULL font program, Flate-compressed.

    ``/Length1`` is the UNCOMPRESSED font length (a CIDFontType2/TrueType
    requirement); ``/Length`` is the compressed stream length. Compression is
    pinned to level 6 (see module docstring). The embedded bytes decompress
    back to ``font_bytes`` verbatim — the font is embedded whole, no subset.
    """
    length1 = len(font_bytes)
    payload = zlib.compress(font_bytes, _FLATE_LEVEL)
    header = (
        f"<< /Length {len(payload)} /Length1 {length1} /Filter /FlateDecode >>\n"
        f"stream\n"
    ).encode("ascii")
    return header + payload + b"\nendstream"


def _tounicode_cmap_body(
    font: TrueTypeFont, gids: list[int], cp_by_gid: dict[int, list[int]]
) -> bytes:
    """Build the ToUnicode CMap stream content (before stream wrapping).

    Standard ``/CIDInit /ProcSet ... begincmap ... beginbfchar ... endcmap``
    shape. Each entry maps a 2-byte source CID (== GID) to a UTF-16BE
    destination. GIDs are iterated in SORTED order; each GID's destination is
    its SMALLEST contributing codepoint (a glyph->text map picks one). GID 0
    (.notdef) is skipped — mapping .notdef to a real character would corrupt
    copy of missing glyphs.
    """
    entries: list[bytes] = []
    for gid in gids:
        if gid == 0:
            continue
        cps = cp_by_gid.get(gid)
        if not cps:
            continue
        cp = cps[0]  # smallest, deterministic
        src = struct.pack(">H", gid).hex().upper()
        dst = _utf16be_hex(cp)
        entries.append(f"<{src}> <{dst}>".encode("ascii"))

    header = (
        b"/CIDInit /ProcSet findresource begin\n"
        b"12 dict begin\n"
        b"begincmap\n"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) "
        b"/Supplement 0 >> def\n"
        b"/CMapName /Adobe-Identity-UCS def\n"
        b"/CMapType 2 def\n"
        b"1 begincodespacerange\n"
        b"<0000> <FFFF>\n"
        b"endcodespacerange\n"
    )
    body = bytearray(header)
    # bfchar entries, in batches of at most 100 (the CMap spec limit).
    for start in range(0, len(entries), 100):
        batch = entries[start : start + 100]
        body += f"{len(batch)} beginbfchar\n".encode("ascii")
        for e in batch:
            body += e + b"\n"
        body += b"endbfchar\n"
    body += b"endcmap\n"
    body += b"CMapName currentdict /CMap defineresource pop\n"
    body += b"end\n"
    body += b"end\n"
    return bytes(body)


def tounicode_stream_object(
    font: TrueTypeFont, gids: list[int], cp_by_gid: dict[int, list[int]]
) -> bytes:
    """Body of the ToUnicode CMap stream object (dict + stream + endstream).

    Flate-compressed at the pinned level for determinism, consistent with
    FontFile2. The decompressed content is the CMap from
    :func:`_tounicode_cmap_body`.
    """
    cmap = _tounicode_cmap_body(font, gids, cp_by_gid)
    payload = zlib.compress(cmap, _FLATE_LEVEL)
    header = (
        f"<< /Length {len(payload)} /Filter /FlateDecode >>\nstream\n"
    ).encode("ascii")
    return header + payload + b"\nendstream"


def _utf16be_hex(cp: int) -> str:
    """Encode a Unicode codepoint as uppercase UTF-16BE hex (1 or 2 units).

    BMP codepoints are one 16-bit unit; astral codepoints become a surrogate
    pair, both units concatenated, as ToUnicode requires.
    """
    if cp <= 0xFFFF:
        return f"{cp:04X}"
    v = cp - 0x10000
    hi = 0xD800 + (v >> 10)
    lo = 0xDC00 + (v & 0x3FF)
    return f"{hi:04X}{lo:04X}"


# --- Convenience: emit the whole font object graph into a PDFWriter -------


@dataclass(frozen=True)
class EmbeddedFontObjects:
    """The object numbers of an embedded font's graph, for cross-referencing.

    ``type0`` is the number a page's ``/Font`` slot references. The rest are
    internal links already wired into the emitted bodies.
    """

    type0: int
    cidfont: int
    descriptor: int
    fontfile2: int
    tounicode: int


def emit_embedded_font(
    writer,
    font: TrueTypeFont,
    font_bytes: bytes,
    codepoints: set[int],
    base_font: str = "InkmdEmbedded",
) -> EmbeddedFontObjects:
    """Register one embedded font's object graph on ``writer`` (a PDFWriter).

    Pure helper for callers/tests/S5: it assigns object numbers via the
    writer's ``add_object`` and wires every cross-reference. UNUSED by the live
    ``styled_pdf`` path. Emission order is fixed (FontFile2, descriptor,
    ToUnicode, CIDFont, Type0) so the numbers are deterministic given the
    writer's current state.

    ``font_bytes`` is the raw font program embedded verbatim; ``font`` is the
    parsed view of the same bytes (caller passes both so we never re-parse).
    Returns the assigned object numbers.
    """
    gids = used_gids(font, codepoints)
    cp_by_gid = gid_to_codepoints(font, codepoints)

    fontfile2_n = writer.add_object(fontfile2_stream_object(font_bytes))
    descriptor_n = writer.add_object(
        font_descriptor_object(font, base_font, fontfile2_n)
    )
    tounicode_n = writer.add_object(
        tounicode_stream_object(font, gids, cp_by_gid)
    )
    cidfont_n = writer.add_object(
        cidfont_object(font, base_font, gids, descriptor_n)
    )
    type0_n = writer.add_object(
        type0_font_object(base_font, cidfont_n, tounicode_n)
    )
    return EmbeddedFontObjects(
        type0=type0_n,
        cidfont=cidfont_n,
        descriptor=descriptor_n,
        fontfile2=fontfile2_n,
        tounicode=tounicode_n,
    )
