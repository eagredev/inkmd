"""Tests for the hand-rolled OpenType/TrueType outline reader (truetype.py).

The reader is only as trustworthy as its test font, so these tests hand-pack
a *real* minimal sfnt with ``struct`` (correct table offsets and lengths, a
valid table directory) and assert the reader reads back exactly the values
that were packed. Fixtures are built to the OpenType spec's byte layout
first; the reader then reads them. No committed test depends on a system
font path.

Coverage: a simple glyph with >1 contour, a composite glyph referencing a
simple one with a known offset, an empty glyph (space), a cmap format-4 and
a cmap format-12, an hmtx tail where ``numberOfHMetrics < numGlyphs``, and
malformed inputs (truncated directory, missing table, OTTO tag).
"""

from __future__ import annotations

import struct

import pytest

from inkmd.truetype import TrueTypeFont, TrueTypeFontError


# --- Synthetic sfnt builder -----------------------------------------------


def _pad4(b: bytes) -> bytes:
    return b + b"\x00" * ((-len(b)) % 4)


def _assemble_sfnt(tables: dict[str, bytes], sfnt_tag: bytes = b"\x00\x01\x00\x00") -> bytes:
    """Assemble a valid sfnt from tag -> table bytes (checksums zeroed).

    Mirrors the ``_build_cbdt_font`` assembly in test_emoji_font.py: a real
    table directory with correct offsets/lengths, 4-byte-padded table data.
    """
    tags = sorted(tables)
    num = len(tags)
    header = struct.pack(">4sHHHH", sfnt_tag, num, 0, 0, 0)
    dir_len = num * 16
    body = b""
    records = b""
    offset = 12 + dir_len
    for tag in tags:
        tbl = tables[tag]
        records += struct.pack(">4sLLL", tag.encode("latin1"), 0, offset, len(tbl))
        padded = _pad4(tbl)
        body += padded
        offset += len(padded)
    return header + records + body


def _head(units_per_em: int = 1000, index_to_loc: int = 0) -> bytes:
    """A 54-byte head table with the two fields the reader reads.

    Layout: version(4) fontRevision(4) checkSumAdjustment(4) magic(4)
    flags(2) unitsPerEm(2)@18 created(8) modified(8) xMin(2) yMin(2) xMax(2)
    yMax(2) macStyle(2) lowestRecPPEM(2) fontDirectionHint(2)
    indexToLocFormat(2)@50 glyphDataFormat(2)@52.
    """
    b = bytearray(54)
    struct.pack_into(">L", b, 0, 0x00010000)
    struct.pack_into(">L", b, 12, 0x5F0F3CF5)  # magic
    struct.pack_into(">H", b, 18, units_per_em)
    struct.pack_into(">h", b, 50, index_to_loc)
    return bytes(b)


def _maxp(num_glyphs: int) -> bytes:
    # version(4) numGlyphs(2)@4 + the rest of the 1.0 fields (zeroed).
    b = bytearray(32)
    struct.pack_into(">L", b, 0, 0x00010000)
    struct.pack_into(">H", b, 4, num_glyphs)
    return bytes(b)


def _hhea(num_h_metrics: int) -> bytes:
    # 36-byte table; numberOfHMetrics is uint16 @ +34.
    b = bytearray(36)
    struct.pack_into(">L", b, 0, 0x00010000)
    struct.pack_into(">H", b, 34, num_h_metrics)
    return bytes(b)


def _hmtx(advances: list[int]) -> bytes:
    # longHorMetric[]: advanceWidth(2) lsb(2). One per explicit metric.
    return b"".join(struct.pack(">Hh", adv, 0) for adv in advances)


def _loca_short(offsets: list[int]) -> bytes:
    # Short loca stores offset/2 as uint16.
    return b"".join(struct.pack(">H", o // 2) for o in offsets)


def _loca_long(offsets: list[int]) -> bytes:
    return b"".join(struct.pack(">L", o) for o in offsets)


def _simple_glyph(contours: list[list[tuple[int, int, bool]]]) -> bytes:
    """Pack a simple glyph from contours of (x, y, on_curve) points.

    Coordinates are written as full 16-bit signed deltas (no short/same
    optimisation) so the layout is unambiguous; the reader's short/same
    paths are covered separately by the DejaVu scratch check and by the
    flag-driven branches still executing on these deltas.
    """
    end_pts = []
    n = 0
    flat: list[tuple[int, int, bool]] = []
    for c in contours:
        n += len(c)
        end_pts.append(n - 1)
        flat.extend(c)
    num_contours = len(contours)
    x_min = min((p[0] for p in flat), default=0)
    y_min = min((p[1] for p in flat), default=0)
    x_max = max((p[0] for p in flat), default=0)
    y_max = max((p[1] for p in flat), default=0)
    out = struct.pack(">hhhhh", num_contours, x_min, y_min, x_max, y_max)
    out += b"".join(struct.pack(">H", e) for e in end_pts)
    out += struct.pack(">H", 0)  # instructionLength = 0
    # Flags: ON_CURVE bit only when on_curve; no short/same, so deltas follow.
    for _x, _y, on in flat:
        out += struct.pack(">B", 0x01 if on else 0x00)
    # X deltas as int16.
    prev = 0
    for x, _y, _on in flat:
        out += struct.pack(">h", x - prev)
        prev = x
    # Y deltas as int16.
    prev = 0
    for _x, y, _on in flat:
        out += struct.pack(">h", y - prev)
        prev = y
    return out


def _composite_glyph(component_gid: int, dx: int, dy: int) -> bytes:
    """A composite glyph: one component, ARGS_ARE_XY_VALUES word args."""
    num_contours = -1
    out = struct.pack(">hhhhh", num_contours, 0, 0, 0, 0)
    # flags: ARG_1_AND_2_ARE_WORDS(0x1) | ARGS_ARE_XY_VALUES(0x2) = 0x3.
    flags = 0x0001 | 0x0002
    out += struct.pack(">HH", flags, component_gid)
    out += struct.pack(">hh", dx, dy)
    return out


def _cmap_format4(mapping: dict[int, int]) -> bytes:
    """A cmap format-4 subtable mapping BMP codepoints to gids.

    Built with one segment per codepoint plus the mandatory 0xFFFF
    terminator segment, all using idRangeOffset == 0 (direct idDelta).
    """
    items = sorted(mapping.items())
    starts = [cp for cp, _ in items] + [0xFFFF]
    ends = [cp for cp, _ in items] + [0xFFFF]
    # idDelta so that (cp + delta) & 0xFFFF == gid.
    deltas = [(gid - cp) & 0xFFFF for cp, gid in items] + [1]
    range_offsets = [0] * len(starts)
    seg_count = len(starts)
    seg_x2 = seg_count * 2

    body = b"".join(struct.pack(">H", e) for e in ends)
    body += struct.pack(">H", 0)  # reservedPad
    body += b"".join(struct.pack(">H", s) for s in starts)
    body += b"".join(struct.pack(">H", d) for d in deltas)
    body += b"".join(struct.pack(">H", r) for r in range_offsets)

    search_range = 2  # not read by the parser; cosmetic
    length = 14 + len(body)
    head = struct.pack(">HHHHHHH", 4, length, 0, seg_x2, search_range, 0, 0)
    return head + body


def _cmap_format12(mapping: dict[int, int]) -> bytes:
    items = sorted(mapping.items())
    groups = b"".join(struct.pack(">LLL", cp, cp, gid) for cp, gid in items)
    length = 16 + len(groups)
    head = struct.pack(">HHLL", 12, 0, length, 0)  # format, reserved, length, language
    return head + struct.pack(">L", len(items)) + groups


def _cmap(format4: dict[int, int] | None = None,
          format12: dict[int, int] | None = None) -> bytes:
    """Assemble a cmap table with optional format-4 and/or format-12 subtables.

    format-4 is exposed as (3,1); format-12 as (3,10).
    """
    subtables: list[tuple[int, int, bytes]] = []
    if format12 is not None:
        subtables.append((3, 10, _cmap_format12(format12)))
    if format4 is not None:
        subtables.append((3, 1, _cmap_format4(format4)))
    n = len(subtables)
    enc_records_len = 4 + n * 8
    out = struct.pack(">HH", 0, n)
    running = enc_records_len
    blobs = b""
    for plat, enc, blob in subtables:
        out += struct.pack(">HHL", plat, enc, running)
        running += len(blob)
        blobs += blob
    return out + blobs


def _build_truetype_font(
    *,
    glyphs: list[bytes],
    advances: list[int],
    num_h_metrics: int,
    units_per_em: int = 1000,
    format4: dict[int, int] | None = None,
    format12: dict[int, int] | None = None,
    long_loca: bool = False,
    sfnt_tag: bytes = b"\x00\x01\x00\x00",
) -> bytes:
    """Hand-pack a minimal but real glyf-flavoured sfnt.

    ``glyphs`` is the per-gid raw glyf bytes (empty bytes = empty glyph);
    ``advances`` seeds hmtx (length == ``num_h_metrics``). loca is computed
    from the (4-byte-aligned) glyph blob sizes.
    """
    num_glyphs = len(glyphs)
    # Build glyf with per-glyph 4-byte alignment (loca offsets must be even
    # for short loca; we align to 4 to be safe).
    glyf = b""
    offsets = [0]
    for g in glyphs:
        glyf += _pad4(g)
        offsets.append(len(glyf))

    index_to_loc = 1 if long_loca else 0
    loca = _loca_long(offsets) if long_loca else _loca_short(offsets)

    tables = {
        "head": _head(units_per_em, index_to_loc),
        "maxp": _maxp(num_glyphs),
        "hhea": _hhea(num_h_metrics),
        "hmtx": _hmtx(advances),
        "loca": loca,
        "glyf": glyf,
        "cmap": _cmap(format4=format4, format12=format12),
    }
    return _assemble_sfnt(tables, sfnt_tag=sfnt_tag)


# A reusable 3-glyph fixture:
#   gid 0: .notdef, empty
#   gid 1: a simple glyph with TWO contours (outer triangle + inner triangle)
#   gid 2: a composite referencing gid 1, translated by (+100, +50)
#   gid 3: an empty glyph (space)
_OUTER = [(0, 0, True), (300, 0, True), (150, 400, True)]
_INNER = [(50, 50, True), (200, 50, True), (125, 250, False)]
_SIMPLE = _simple_glyph([_OUTER, _INNER])
_COMPOSITE = _composite_glyph(component_gid=1, dx=100, dy=50)


def _standard_font(**kwargs) -> TrueTypeFont:
    glyphs = [b"", _SIMPLE, _COMPOSITE, b""]
    return TrueTypeFont(_build_truetype_font(
        glyphs=glyphs,
        advances=[600, 700],          # only 2 explicit metrics...
        num_h_metrics=2,               # ...so gids 2,3 reuse advance 700
        format4={0x41: 1, 0x42: 2, 0x20: 3},
        **kwargs,
    ))


# --- Header / scalar tests ------------------------------------------------


def test_table_directory_parsed():
    font = _standard_font()
    assert set(font.tables) >= {
        "head", "maxp", "hhea", "hmtx", "loca", "glyf", "cmap"
    }


def test_units_per_em_and_num_glyphs():
    font = _standard_font(units_per_em=2048)
    assert font.units_per_em == 2048
    assert font.num_glyphs == 4


# --- cmap format-4 --------------------------------------------------------


def test_cmap_format4_lookup():
    font = _standard_font()
    assert font.glyph_id(0x41) == 1   # 'A'
    assert font.glyph_id(0x42) == 2   # 'B'
    assert font.glyph_id(0x20) == 3   # space
    assert font.glyph_id(0x5A) == 0   # 'Z' unmapped -> .notdef


def test_cmap_format4_astral_returns_zero():
    font = _standard_font()
    # format 4 only covers the BMP; an astral codepoint must miss cleanly.
    assert font.glyph_id(0x1F680) == 0


# --- cmap format-12 -------------------------------------------------------


def test_cmap_format12_lookup():
    glyphs = [b"", _SIMPLE, _COMPOSITE]
    font = TrueTypeFont(_build_truetype_font(
        glyphs=glyphs,
        advances=[600, 700, 700],
        num_h_metrics=3,
        format12={0x41: 1, 0x1F680: 2},  # BMP + astral
    ))
    assert font.glyph_id(0x41) == 1
    assert font.glyph_id(0x1F680) == 2   # astral codepoint via format 12
    assert font.glyph_id(0x42) == 0


def test_cmap_prefers_format12_over_format4():
    # Same codepoint maps to different gids in each subtable; format 12 wins.
    glyphs = [b"", _SIMPLE, _COMPOSITE]
    font = TrueTypeFont(_build_truetype_font(
        glyphs=glyphs,
        advances=[600, 700, 700],
        num_h_metrics=3,
        format4={0x41: 1},
        format12={0x41: 2},
    ))
    assert font.glyph_id(0x41) == 2


# --- hmtx (advance widths, incl. reused tail) -----------------------------


def test_advance_width_explicit_and_reused_tail():
    font = _standard_font()
    assert font.advance_width(0) == 600
    assert font.advance_width(1) == 700
    # gids 2 and 3 are past numberOfHMetrics -> reuse the last advance (700).
    assert font.advance_width(2) == 700
    assert font.advance_width(3) == 700


def test_advance_width_out_of_range_raises():
    font = _standard_font()
    with pytest.raises(TrueTypeFontError):
        font.advance_width(99)


# --- glyf: simple glyph ---------------------------------------------------


def test_simple_glyph_two_contours():
    font = _standard_font()
    contours = font.glyph_outline(1)
    assert len(contours) == 2
    outer = [(p.x, p.y, p.on_curve) for p in contours[0]]
    inner = [(p.x, p.y, p.on_curve) for p in contours[1]]
    assert outer == _OUTER
    assert inner == _INNER
    # The off-curve point in the inner contour is preserved.
    assert contours[1][2].on_curve is False


# --- glyf: composite glyph ------------------------------------------------


def test_composite_glyph_offset_applied():
    font = _standard_font()
    contours = font.glyph_outline(2)
    # Same shape as gid 1 but every point shifted by (+100, +50).
    assert len(contours) == 2
    outer = [(p.x, p.y, p.on_curve) for p in contours[0]]
    expected = [(x + 100, y + 50, on) for (x, y, on) in _OUTER]
    assert outer == expected
    inner = [(p.x, p.y, p.on_curve) for p in contours[1]]
    expected_inner = [(x + 100, y + 50, on) for (x, y, on) in _INNER]
    assert inner == expected_inner


# --- glyf: empty glyph ----------------------------------------------------


def test_empty_glyph_zero_contours():
    font = _standard_font()
    assert font.glyph_outline(3) == []   # space, loca length 0
    assert font.glyph_outline(0) == []   # .notdef, empty here too


def test_glyph_outline_cached():
    font = _standard_font()
    a = font.glyph_outline(1)
    b = font.glyph_outline(1)
    assert a is b


# --- long loca ------------------------------------------------------------


def test_long_loca_format():
    font = _standard_font(long_loca=True)
    # Same outlines, but loca is now uint32 (indexToLocFormat == 1).
    assert font.glyph_outline(1) and len(font.glyph_outline(1)) == 2
    assert font.glyph_outline(3) == []


# --- malformed inputs -----------------------------------------------------


def test_otto_tag_raises():
    blob = _build_truetype_font(
        glyphs=[b"", _SIMPLE],
        advances=[600, 700],
        num_h_metrics=2,
        format4={0x41: 1},
        sfnt_tag=b"OTTO",
    )
    font = TrueTypeFont(blob)
    with pytest.raises(TrueTypeFontError, match="CFF"):
        font.tables


def test_truncated_directory_raises():
    # Claims 5 tables but provides no records.
    blob = b"\x00\x01\x00\x00" + struct.pack(">HHHH", 5, 0, 0, 0)
    font = TrueTypeFont(blob)
    with pytest.raises(TrueTypeFontError):
        font.tables


def test_too_short_for_header_raises():
    font = TrueTypeFont(b"\x00\x01")
    with pytest.raises(TrueTypeFontError):
        font.tables


def test_missing_required_table_raises():
    # A valid directory but no glyf table -> reading an outline must raise.
    tables = {
        "head": _head(),
        "maxp": _maxp(2),
        "hhea": _hhea(2),
        "hmtx": _hmtx([600, 700]),
        "loca": _loca_short([0, 0, 0]),
        "cmap": _cmap(format4={0x41: 1}),
        # no glyf
    }
    font = TrueTypeFont(_assemble_sfnt(tables))
    with pytest.raises(TrueTypeFontError, match="glyf"):
        font.glyph_outline(1)


def test_missing_head_raises():
    tables = {
        "maxp": _maxp(1),
        "cmap": _cmap(format4={0x41: 1}),
    }
    font = TrueTypeFont(_assemble_sfnt(tables))
    with pytest.raises(TrueTypeFontError, match="head"):
        font.units_per_em


def test_font_without_cmap_subtable_raises():
    # cmap header present but zero subtables.
    empty_cmap = struct.pack(">HH", 0, 0)
    tables = {
        "head": _head(),
        "maxp": _maxp(1),
        "hhea": _hhea(1),
        "hmtx": _hmtx([600]),
        "loca": _loca_short([0, 0]),
        "glyf": b"",
        "cmap": empty_cmap,
    }
    font = TrueTypeFont(_assemble_sfnt(tables))
    with pytest.raises(TrueTypeFontError):
        font.glyph_id(0x41)
