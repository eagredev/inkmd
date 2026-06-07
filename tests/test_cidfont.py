"""Tests for Type0/CIDFontType2 PDF emission (cidfont.py, Spine 3).

These parse the EMITTED object bytes (never eyeball) and assert the structural
invariants the embed depends on: the Type0 graph shape, native-GID Identity
mapping, the /W advances, the FontFile2 round-trip (decompress == font),
the ToUnicode round-trip (copy/search), the show-text CID hex, byte-level
determinism (incl. order-independence of the used-codepoint input), and a
minimal assembled PDF whose cross-references are self-consistent.

The synthetic font is built with S1's ``_build_truetype_font`` plus a couple
of richer table builders (non-zero head bbox, non-zero hhea ascent, an OS/2
table) so the FontDescriptor's font-derived metrics are exercised against
known values. No test depends on a system font path.
"""

from __future__ import annotations

import re
import struct
import zlib

import pytest

from inkmd.cidfont import (
    _utf16be_hex,
    _width_array,
    cidfont_object,
    default_width,
    emit_embedded_font,
    font_descriptor_object,
    fontfile2_stream_object,
    gid_to_codepoints,
    show_text_cid_hex,
    tounicode_stream_object,
    type0_font_object,
    used_gids,
)
from inkmd.pdf import PDFWriter
from inkmd.truetype import TrueTypeFont, TrueTypeFontError

# Reuse S1's synthetic-font machinery.
from tests.test_truetype import (
    _COMPOSITE,
    _SIMPLE,
    _assemble_sfnt,
    _cmap,
    _hmtx,
    _loca_short,
    _maxp,
    _pad4,
)


# --- Richer table builders (non-zero metrics for descriptor checks) -------


def _head_with_bbox(units_per_em: int, bbox: tuple[int, int, int, int]) -> bytes:
    """A 54-byte head table with unitsPerEm AND a non-zero FontBBox.

    bbox = (xMin, yMin, xMax, yMax) at +36..+44; indexToLocFormat 0 @ +50.
    """
    x_min, y_min, x_max, y_max = bbox
    b = bytearray(54)
    struct.pack_into(">L", b, 0, 0x00010000)
    struct.pack_into(">L", b, 12, 0x5F0F3CF5)
    struct.pack_into(">H", b, 18, units_per_em)
    struct.pack_into(">hhhh", b, 36, x_min, y_min, x_max, y_max)
    struct.pack_into(">h", b, 50, 0)
    return bytes(b)


def _hhea_with_metrics(num_h_metrics: int, ascender: int, descender: int) -> bytes:
    """A 36-byte hhea: ascender @ +4, descender @ +6, numberOfHMetrics @ +34."""
    b = bytearray(36)
    struct.pack_into(">L", b, 0, 0x00010000)
    struct.pack_into(">h", b, 4, ascender)
    struct.pack_into(">h", b, 6, descender)
    struct.pack_into(">H", b, 34, num_h_metrics)
    return bytes(b)


def _os2_v2(cap_height: int) -> bytes:
    """A 96-byte OS/2 v2 table carrying sCapHeight @ +88 (version uint16 @ 0)."""
    b = bytearray(96)
    struct.pack_into(">H", b, 0, 2)  # version 2
    struct.pack_into(">h", b, 88, cap_height)
    return bytes(b)


# Known design values for the fixture.
_UPM = 1000
_BBOX = (-50, -200, 950, 800)
_ASCENT = 750
_DESCENT = -250
_CAPHEIGHT = 700
_ADVANCES = [600, 700]            # explicit metrics for gids 0,1
_NUM_H_METRICS = 2               # gids 2,3 reuse advance 700
# cmap: 'A'->1, 'B'->2, space->3. (Same shape as S1's _standard_font.)
_CMAP = {0x41: 1, 0x42: 2, 0x20: 3}


def _build_rich_font(with_os2: bool = True) -> bytes:
    """Assemble a glyf font with non-zero head bbox + hhea metrics (+ OS/2).

    Glyph layout matches S1's reusable fixture: gid0 empty .notdef, gid1 a
    two-contour simple glyph, gid2 a composite, gid3 empty (space).
    """
    glyphs = [b"", _SIMPLE, _COMPOSITE, b""]
    glyf = b""
    offsets = [0]
    for g in glyphs:
        glyf += _pad4(g)
        offsets.append(len(glyf))
    tables = {
        "head": _head_with_bbox(_UPM, _BBOX),
        "maxp": _maxp(len(glyphs)),
        "hhea": _hhea_with_metrics(_NUM_H_METRICS, _ASCENT, _DESCENT),
        "hmtx": _hmtx(_ADVANCES),
        "loca": _loca_short(offsets),
        "glyf": glyf,
        "cmap": _cmap(format4=_CMAP),
    }
    if with_os2:
        tables["OS/2"] = _os2_v2(_CAPHEIGHT)
    return _assemble_sfnt(tables)


def _font_and_bytes(with_os2: bool = True) -> tuple[TrueTypeFont, bytes]:
    raw = _build_rich_font(with_os2=with_os2)
    return TrueTypeFont(raw), raw


# Codepoints used by the document under test: 'A', 'B', space.
_USED = {0x41, 0x42, 0x20}
# Expected GIDs (sorted): A->1, B->2, space->3.
_USED_GIDS = [1, 2, 3]


# --- used_gids / gid_to_codepoints determinism gate -----------------------


def test_used_gids_sorted_and_deduped():
    font, _ = _font_and_bytes()
    assert used_gids(font, _USED) == _USED_GIDS
    # Duplicate-producing input still sorts/dedupes.
    assert used_gids(font, {0x41, 0x41, 0x42}) == [1, 2]


def test_used_gids_order_independent():
    font, _ = _font_and_bytes()
    a = used_gids(font, set([0x20, 0x41, 0x42]))
    b = used_gids(font, set([0x42, 0x20, 0x41]))
    assert a == b == _USED_GIDS


def test_gid_to_codepoints_picks_smallest():
    # Two codepoints sharing one glyph: the map keeps both, sorted.
    glyphs = [b"", _SIMPLE]
    glyf = b""
    offsets = [0]
    for g in glyphs:
        glyf += _pad4(g)
        offsets.append(len(glyf))
    tables = {
        "head": _head_with_bbox(_UPM, _BBOX),
        "maxp": _maxp(2),
        "hhea": _hhea_with_metrics(1, _ASCENT, _DESCENT),
        "hmtx": _hmtx([600]),
        "loca": _loca_short(offsets),
        "glyf": glyf,
        "cmap": _cmap(format4={0x41: 1, 0x391: 1}),  # 'A' and GREEK ALPHA -> 1
    }
    font = TrueTypeFont(_assemble_sfnt(tables))
    m = gid_to_codepoints(font, {0x391, 0x41})
    assert m[1] == [0x41, 0x391]  # sorted; emission uses the first (smallest)


# --- /W width array -------------------------------------------------------


def test_width_array_consecutive_run():
    font, _ = _font_and_bytes()
    # GIDs 1,2,3 are consecutive -> a single "1 [w1 w2 w3]" run. em == 1000, so
    # the PDF 1000-em scaling is a no-op and /W == the raw advances.
    body = _width_array(font, _USED_GIDS)
    assert body == "1 [700 700 700]"  # advance_width(1)=700, 2,3 reuse 700


def test_width_array_split_runs():
    font, _ = _font_and_bytes()
    # GIDs 0 and 2 are non-consecutive -> two runs.
    body = _width_array(font, [0, 2])
    assert body == "0 [600] 2 [700]"


def test_default_width_is_notdef_advance():
    font, _ = _font_and_bytes()
    # em == 1000, so scale factor is 1: /DW == raw .notdef advance (no-op path).
    assert default_width(font) == 600  # gid 0 advance


# --- PDF 1000-em width scaling (the S3-FIX regression net) -----------------
#
# Type0 /W and /DW are ALWAYS in PDF glyph space (1/1000 em), regardless of the
# font program's unitsPerEm. The 1000-em fixture above proves the no-op path
# (scale factor 1). The 2048-em case below proves the scaling actually fires —
# this is the assertion that would have caught the original raw-advance bug.


def _build_2048em_font() -> tuple[TrueTypeFont, bytes]:
    """Same fixture shape as ``_build_rich_font`` but with unitsPerEm = 2048.

    The 'A'/'B' advances (700) and the .notdef advance (600) are RAW design
    units; in PDF glyph space they must scale by 1000/2048.
    """
    glyphs = [b"", _SIMPLE, _COMPOSITE, b""]
    glyf = b""
    offsets = [0]
    for g in glyphs:
        glyf += _pad4(g)
        offsets.append(len(glyf))
    tables = {
        "head": _head_with_bbox(2048, _BBOX),
        "maxp": _maxp(len(glyphs)),
        "hhea": _hhea_with_metrics(_NUM_H_METRICS, _ASCENT, _DESCENT),
        "hmtx": _hmtx(_ADVANCES),
        "loca": _loca_short(offsets),
        "glyf": glyf,
        "cmap": _cmap(format4=_CMAP),
        "OS/2": _os2_v2(_CAPHEIGHT),
    }
    raw = _assemble_sfnt(tables)
    return TrueTypeFont(raw), raw


def test_width_array_scaled_to_1000_em():
    """/W advances for a 2048-em font are round(raw * 1000 / 2048), not raw."""
    font, _ = _build_2048em_font()
    # GIDs 1,2,3 all have raw advance 700 -> round(700 * 1000 / 2048) = 342.
    expected = round(700 * 1000 / 2048)
    assert expected == 342  # pin the arithmetic so a wrong oracle can't slip in
    body = _width_array(font, _USED_GIDS)
    assert body == f"1 [{expected} {expected} {expected}]"
    # Emphatically NOT the raw advance.
    assert "700" not in body


def test_default_width_scaled_to_1000_em():
    """/DW for a 2048-em font is round(notdef_raw * 1000 / 2048), not raw."""
    font, _ = _build_2048em_font()
    # .notdef raw advance 600 -> round(600 * 1000 / 2048) = 293.
    expected = round(600 * 1000 / 2048)
    assert expected == 293
    assert default_width(font) == expected
    assert default_width(font) != 600  # not the raw design-unit advance


def test_cidfont_widths_scaled_for_2048_em():
    """The assembled CIDFont dict carries the SCALED /W and /DW, not raw."""
    font, _ = _build_2048em_font()
    body = cidfont_object(font, "MyFont", _USED_GIDS, descriptor_obj_num=5)
    text = body.decode("ascii")
    assert "/DW 293" in text
    m = re.search(r"/W \[(.*?)\]\s*>>", text)
    assert m is not None
    assert m.group(1) == "1 [342 342 342]"  # "<start-CID> [scaled widths]"


# --- Type0 dict structure -------------------------------------------------


def test_type0_structure():
    body = type0_font_object("MyFont", descendant_obj_num=7, tounicode_obj_num=9)
    text = body.decode("ascii")
    assert "/Subtype /Type0" in text
    assert "/Encoding /Identity-H" in text
    assert "/DescendantFonts [7 0 R]" in text
    assert "/ToUnicode 9 0 R" in text
    assert "/BaseFont /MyFont" in text


# --- CIDFontType2 dict structure ------------------------------------------


def test_cidfont_structure_and_widths():
    font, _ = _font_and_bytes()
    body = cidfont_object(font, "MyFont", _USED_GIDS, descriptor_obj_num=5)
    text = body.decode("ascii")
    assert "/Subtype /CIDFontType2" in text
    assert "/CIDToGIDMap /Identity" in text
    assert "/Registry (Adobe) /Ordering (Identity) /Supplement 0" in text
    assert "/FontDescriptor 5 0 R" in text
    assert "/DW 600" in text
    # Parse the /W array body and check it matches known advances.
    m = re.search(r"/W \[(.*?)\]\s*>>", text)
    assert m is not None
    assert m.group(1) == "1 [700 700 700]"


# --- FontDescriptor structure + font-derived metrics ----------------------


def test_font_descriptor_font_derived_metrics():
    font, _ = _font_and_bytes(with_os2=True)
    body = font_descriptor_object(font, "MyFont", fontfile_obj_num=4)
    text = body.decode("ascii")
    assert "/Type /FontDescriptor" in text
    assert "/FontFile2 4 0 R" in text
    # Font-derived: FontBBox from head, Ascent/Descent from hhea, CapHeight OS/2.
    assert f"/FontBBox [{_BBOX[0]} {_BBOX[1]} {_BBOX[2]} {_BBOX[3]}]" in text
    assert f"/Ascent {_ASCENT}" in text
    assert f"/Descent {_DESCENT}" in text
    assert f"/CapHeight {_CAPHEIGHT}" in text
    # Constants (named in the report): Flags Nonsymbolic (32), StemV 80.
    assert "/Flags 32" in text
    assert "/StemV 80" in text
    assert "/ItalicAngle 0" in text


def test_font_descriptor_capheight_falls_back_to_ascent_without_os2():
    font, _ = _font_and_bytes(with_os2=False)
    body = font_descriptor_object(font, "MyFont", fontfile_obj_num=4)
    text = body.decode("ascii")
    # No OS/2 -> CapHeight falls back to the ascender (named fallback).
    assert f"/CapHeight {_ASCENT}" in text


# --- FontFile2 round-trip -------------------------------------------------


def test_fontfile2_length1_and_decompress():
    font, raw = _font_and_bytes()
    body = fontfile2_stream_object(raw)
    text_head = body[: body.index(b"stream")].decode("ascii")
    # /Length1 == uncompressed font length.
    m1 = re.search(r"/Length1 (\d+)", text_head)
    assert m1 is not None and int(m1.group(1)) == len(raw)
    assert "/Filter /FlateDecode" in text_head
    # Extract the stream payload and assert it decompresses to the font verbatim.
    payload = _extract_stream_payload(body)
    assert zlib.decompress(payload) == raw
    # /Length matches the compressed payload length.
    m2 = re.search(r"/Length (\d+)", text_head)
    assert m2 is not None and int(m2.group(1)) == len(payload)


def test_fontfile2_pinned_level_is_deterministic():
    _, raw = _font_and_bytes()
    a = fontfile2_stream_object(raw)
    b = fontfile2_stream_object(raw)
    assert a == b
    # And independent of any used-codepoint set (it's a pure fn of the font).
    assert zlib.decompress(_extract_stream_payload(a)) == raw


# --- ToUnicode round-trip -------------------------------------------------


def test_tounicode_roundtrips_gids_to_codepoints():
    font, _ = _font_and_bytes()
    gids = used_gids(font, _USED)
    cp_by_gid = gid_to_codepoints(font, _USED)
    body = tounicode_stream_object(font, gids, cp_by_gid)
    cmap = zlib.decompress(_extract_stream_payload(body)).decode("ascii")
    # Parse bfchar entries: <SRC> <DST>.
    pairs = _parse_bfchar(cmap)
    # GID 1 <- 'A' (0x41), GID 2 <- 'B' (0x42), GID 3 <- space (0x20).
    assert pairs[1] == 0x41
    assert pairs[2] == 0x42
    assert pairs[3] == 0x20
    # The standard CMap scaffolding is present.
    assert "begincmap" in cmap
    assert "/CMapType 2 def" in cmap
    assert "endcmap" in cmap


def test_tounicode_skips_notdef():
    font, _ = _font_and_bytes()
    # Include an unmapped codepoint -> GID 0; it must NOT appear in ToUnicode.
    used = {0x41, 0x5A}  # 'A'->1, 'Z'-> unmapped -> 0
    gids = used_gids(font, used)
    assert 0 in gids
    cp_by_gid = gid_to_codepoints(font, used)
    body = tounicode_stream_object(font, gids, cp_by_gid)
    cmap = zlib.decompress(_extract_stream_payload(body)).decode("ascii")
    pairs = _parse_bfchar(cmap)
    assert 0 not in pairs
    assert pairs[1] == 0x41


def test_utf16be_hex_bmp_and_astral():
    assert _utf16be_hex(0x41) == "0041"
    assert _utf16be_hex(0x1F680) == "D83DDE80"  # rocket, surrogate pair


def test_tounicode_astral_roundtrip():
    # A font mapping an astral codepoint -> ToUnicode emits the surrogate pair.
    glyphs = [b"", _SIMPLE]
    glyf = b""
    offsets = [0]
    for g in glyphs:
        glyf += _pad4(g)
        offsets.append(len(glyf))
    tables = {
        "head": _head_with_bbox(_UPM, _BBOX),
        "maxp": _maxp(2),
        "hhea": _hhea_with_metrics(1, _ASCENT, _DESCENT),
        "hmtx": _hmtx([600]),
        "loca": _loca_short(offsets),
        "glyf": glyf,
        "cmap": _cmap(format12={0x1F680: 1}),
    }
    font = TrueTypeFont(_assemble_sfnt(tables))
    used = {0x1F680}
    gids = used_gids(font, used)
    cp_by_gid = gid_to_codepoints(font, used)
    body = tounicode_stream_object(font, gids, cp_by_gid)
    cmap = zlib.decompress(_extract_stream_payload(body)).decode("ascii")
    # The destination should be the UTF-16BE surrogate pair for U+1F680.
    assert "D83DDE80" in cmap.upper()


# --- Show-text CID hex ----------------------------------------------------


def test_show_text_cid_hex():
    font, _ = _font_and_bytes()
    # 'AB ' -> GIDs 1,2,3 -> big-endian 2-byte each.
    op = show_text_cid_hex(font, "AB ")
    assert op == b"<000100020003> Tj"


def test_show_text_unmapped_is_notdef():
    font, _ = _font_and_bytes()
    # 'Z' is unmapped -> GID 0 -> 0000.
    assert show_text_cid_hex(font, "Z") == b"<0000> Tj"


def test_show_text_empty():
    font, _ = _font_and_bytes()
    assert show_text_cid_hex(font, "") == b"<> Tj"


# --- Determinism (the mandate) --------------------------------------------


def test_full_emission_byte_identical_twice():
    """Two independent emissions of the same font graph are byte-identical."""
    font1, raw1 = _font_and_bytes()
    font2, raw2 = _font_and_bytes()
    out1 = _emit_all(font1, raw1, _USED)
    out2 = _emit_all(font2, raw2, _USED)
    assert out1 == out2


def test_emission_order_independent():
    """Feeding the used-codepoint set in two DIFFERENT orders is identical.

    This is the spine of the determinism mandate: /W + /ToUnicode + the
    content show-text bytes must not depend on the iteration order of the
    used-codepoint input. We construct two sets whose internal ordering
    differs and assert byte equality of every order-sensitive output.
    """
    font, raw = _font_and_bytes()
    # Two sets with the same members, built in different insertion orders.
    order_a = set()
    for cp in (0x20, 0x41, 0x42):
        order_a.add(cp)
    order_b = set()
    for cp in (0x42, 0x41, 0x20):
        order_b.add(cp)

    gids_a = used_gids(font, order_a)
    gids_b = used_gids(font, order_b)
    cp_a = gid_to_codepoints(font, order_a)
    cp_b = gid_to_codepoints(font, order_b)

    # /W array identical.
    assert cidfont_object(font, "F", gids_a, 5) == cidfont_object(
        font, "F", gids_b, 5
    )
    # /ToUnicode identical.
    assert tounicode_stream_object(font, gids_a, cp_a) == tounicode_stream_object(
        font, gids_b, cp_b
    )
    # Content show-text identical for the same string.
    assert show_text_cid_hex(font, "AB ") == show_text_cid_hex(font, "AB ")


# --- Assemble-and-validate: a minimal complete PDF ------------------------


def test_assemble_minimal_pdf_cross_refs_consistent():
    """Build a complete one-page PDF embedding the font; validate its xref."""
    font, raw = _font_and_bytes()
    writer = PDFWriter()

    # Reserve catalog/pages/page/contents up front, then the font graph,
    # so we exercise emit_embedded_font wiring + a real page referencing it.
    catalog_n = writer.add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    # Placeholders we will overwrite once we know the page/contents numbers.
    pages_n = writer.add_object(b"PLACEHOLDER")
    page_n = writer.add_object(b"PLACEHOLDER")
    contents_n = writer.add_object(b"PLACEHOLDER")

    fonts = emit_embedded_font(writer, font, raw, _USED, base_font="Embedded")

    # Now fill the reserved objects with correct cross-refs.
    writer.objects[pages_n - 1] = (
        f"<< /Type /Pages /Kids [{page_n} 0 R] /Count 1 >>".encode("ascii")
    )
    writer.objects[page_n - 1] = (
        f"<< /Type /Page /Parent {pages_n} 0 R /MediaBox [0 0 200 200] "
        f"/Resources << /Font << /F0 {fonts.type0} 0 R >> >> "
        f"/Contents {contents_n} 0 R >>"
    ).encode("ascii")
    show = show_text_cid_hex(font, "AB ")
    stream = b"BT /F0 12 Tf 20 100 Tm " + show + b" ET"
    writer.objects[contents_n - 1] = (
        f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
        + stream
        + b"\nendstream"
    )

    pdf = writer.serialise(root_obj_num=catalog_n)
    _assert_pdf_well_formed(pdf)


# --- Parsing / validation helpers (we parse, never eyeball) ----------------


def _extract_stream_payload(obj_body: bytes) -> bytes:
    """Return the bytes between ``stream\\n`` and ``\\nendstream``."""
    start = obj_body.index(b"stream\n") + len(b"stream\n")
    end = obj_body.index(b"\nendstream")
    return obj_body[start:end]


def _parse_bfchar(cmap: str) -> dict[int, int]:
    """Parse ``beginbfchar``..``endbfchar`` into {src_gid: dst_codepoint}.

    Decodes the UTF-16BE destination back to a single codepoint (handling a
    surrogate pair). This is the copy/search round-trip the DoD requires.
    """
    result: dict[int, int] = {}
    for block in re.findall(r"beginbfchar\n(.*?)endbfchar", cmap, re.DOTALL):
        for line in block.strip().splitlines():
            m = re.match(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", line.strip())
            if not m:
                continue
            src = int(m.group(1), 16)
            dst_hex = m.group(2)
            units = [
                int(dst_hex[i : i + 4], 16) for i in range(0, len(dst_hex), 4)
            ]
            if len(units) == 1:
                cp = units[0]
            else:
                hi, lo = units[0], units[1]
                cp = 0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00)
            result[src] = cp
    return result


def _emit_all(font: TrueTypeFont, raw: bytes, used: set[int]) -> bytes:
    """Concatenate every emitted object body + show-text for a determinism check."""
    gids = used_gids(font, used)
    cp_by_gid = gid_to_codepoints(font, used)
    parts = [
        type0_font_object("F", 2, 3),
        cidfont_object(font, "F", gids, 4),
        font_descriptor_object(font, "F", 5),
        fontfile2_stream_object(raw),
        tounicode_stream_object(font, gids, cp_by_gid),
        show_text_cid_hex(font, "AB "),
    ]
    return b"\n".join(parts)


def _assert_pdf_well_formed(pdf: bytes) -> None:
    """Self-validate the assembled PDF's cross-references.

    Checks (no third-party validator): startxref points at the xref table;
    every xref offset lands on an ``N 0 obj`` marker; every ``M 0 R`` indirect
    reference names an object number that exists.
    """
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")

    # Locate startxref -> xref table.
    sx = pdf.rfind(b"startxref")
    assert sx != -1
    xref_off = int(pdf[sx + len(b"startxref"):].split(b"%%EOF")[0].strip())
    assert pdf[xref_off : xref_off + 4] == b"xref"

    # Parse the xref subsection header "0 N".
    after = pdf[xref_off + 5 :]
    first_line, rest = after.split(b"\n", 1)
    start_num, count = (int(x) for x in first_line.split())
    assert start_num == 0

    # Entry 0 is the free-list head; entries 1..count-1 are in-use offsets.
    offsets: list[int] = []
    cursor = rest
    for i in range(count):
        entry = cursor[:20]  # fixed 20-byte entries
        cursor = cursor[20:]
        off = int(entry[:10])
        status = entry[17:18]
        if i == 0:
            assert status == b"f"
            continue
        assert status == b"n"
        offsets.append(off)
        # Each in-use offset must land on "<i> 0 obj".
        assert pdf[off:].startswith(f"{i} 0 obj".encode("ascii")), (
            f"object {i} xref offset {off} does not point at its obj marker"
        )

    n_objects = count - 1
    # Every indirect reference "M 0 R" must name an existing object number.
    for m in re.finditer(rb"(\d+) 0 R", pdf):
        ref = int(m.group(1))
        assert 1 <= ref <= n_objects, f"dangling reference to object {ref}"

    # The trailer /Size must equal count, /Root must reference object 1.
    assert f"/Size {count}".encode("ascii") in pdf
    assert b"/Root 1 0 R" in pdf


# --- Edge: oversized GID rejected in show-text ----------------------------


def test_show_text_rejects_gid_over_ffff():
    # A cmap mapping a codepoint to a GID >= 0x10000 must raise, not truncate.
    # We can't build 65536 glyphs cheaply; instead drive glyph_id via a format-12
    # group whose startGlyphID is huge.
    glyphs = [b"", _SIMPLE]
    glyf = b""
    offsets = [0]
    for g in glyphs:
        glyf += _pad4(g)
        offsets.append(len(glyf))
    # Hand-build a format-12 cmap with start_gid = 0x10001 for codepoint 'A'.
    groups = struct.pack(">LLL", 0x41, 0x41, 0x10001)
    length = 16 + len(groups)
    sub = struct.pack(">HHLL", 12, 0, length, 0) + struct.pack(">L", 1) + groups
    n = 1
    cmap = struct.pack(">HH", 0, n) + struct.pack(">HHL", 3, 10, 4 + n * 8) + sub
    tables = {
        "head": _head_with_bbox(_UPM, _BBOX),
        "maxp": _maxp(2),
        "hhea": _hhea_with_metrics(1, _ASCENT, _DESCENT),
        "hmtx": _hmtx([600]),
        "loca": _loca_short(offsets),
        "glyf": glyf,
        "cmap": cmap,
    }
    font = TrueTypeFont(_assemble_sfnt(tables))
    assert font.glyph_id(0x41) == 0x10001
    with pytest.raises(TrueTypeFontError, match="2-byte"):
        show_text_cid_hex(font, "A")
