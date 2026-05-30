"""Tests for the hand-rolled OpenType color-emoji reader (emoji_font.py).

The reader parses CBDT/CBLC color fonts (Noto Color Emoji et al.) to map
codepoints to glyphs and extract per-glyph PNGs. To stay portable and
reproducible the tests build a *minimal* synthetic CBDT font in memory
rather than depending on a system font: a table directory + cmap (formats
12 and 14) + CBLC (one strike) + CBDT (one PNG glyph). This exercises the
real parser end to end without shipping a binary fixture.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from inkmd.emoji_font import EmojiFont, EmojiFontError


# --- Minimal synthetic CBDT font builder ----------------------------------


def _tiny_png(w: int = 4, h: int = 4) -> bytes:
    """A minimal valid RGB PNG (content irrelevant; just needs the sig)."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    rows = (b"\x00" + b"\xff\x00\x00" * w) * h
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def _build_gsub_ligatures(ligatures: dict[tuple[int, ...], int]) -> bytes:
    """Build a minimal GSUB table with one type-4 (ligature) lookup holding
    the given component-gid-tuple -> ligature-gid mappings.

    Layout: header -> (empty) script/feature lists -> lookup list -> one
    lookup -> one ligature subtable (format 1) with a format-1 coverage of
    first-component gids and one LigatureSet per first component.
    """
    # Group ligatures by their first component glyph.
    by_first: dict[int, list[tuple[tuple[int, ...], int]]] = {}
    for comps, lig_gid in ligatures.items():
        by_first.setdefault(comps[0], []).append((comps, lig_gid))
    first_gids = sorted(by_first)

    # --- Ligature subtable (format 1) ---
    # Build each LigatureSet, then the subtable referencing them.
    ligset_blobs: list[bytes] = []
    for fg in first_gids:
        entries = by_first[fg]
        # Ligature records: ligGlyph(2) compCount(2) componentGlyphs[compCount-1](2 each)
        lig_blobs = []
        for comps, lig_gid in entries:
            rest = comps[1:]
            lig_blobs.append(struct.pack(">HH", lig_gid, len(comps)) + b"".join(struct.pack(">H", g) for g in rest))
        # LigatureSet: ligatureCount(2) ligatureOffsets[](2 each) then ligatures
        n = len(lig_blobs)
        offs_start = 2 + n * 2
        offsets = []
        running = offs_start
        for lb in lig_blobs:
            offsets.append(running)
            running += len(lb)
        ligset = struct.pack(">H", n) + b"".join(struct.pack(">H", o) for o in offsets) + b"".join(lig_blobs)
        ligset_blobs.append(ligset)

    # Coverage format 1: format(2) glyphCount(2) glyphArray[](2 each)
    coverage = struct.pack(">HH", 1, len(first_gids)) + b"".join(struct.pack(">H", g) for g in first_gids)

    # LigatureSubst format 1: substFormat(2) coverageOffset(2) ligSetCount(2)
    # ligatureSetOffsets[](2 each), then coverage, then ligature sets.
    n_sets = len(ligset_blobs)
    subhdr_len = 6 + n_sets * 2
    cov_off = subhdr_len
    sets_off = cov_off + len(coverage)
    set_offsets = []
    running = sets_off
    for sb in ligset_blobs:
        set_offsets.append(running)
        running += len(sb)
    subtable = (
        struct.pack(">HHH", 1, cov_off, n_sets)
        + b"".join(struct.pack(">H", o) for o in set_offsets)
        + coverage
        + b"".join(ligset_blobs)
    )

    # Lookup: lookupType(2) lookupFlag(2) subTableCount(2) subtableOffsets[](2)
    lookup = struct.pack(">HHH", 4, 0, 1) + struct.pack(">H", 8) + subtable  # offset 8 = past header
    # LookupList: lookupCount(2) lookupOffsets[](2)
    lookup_list = struct.pack(">H", 1) + struct.pack(">H", 4) + lookup  # one lookup at offset 4
    # ScriptList + FeatureList: empty (count 0).
    script_list = struct.pack(">H", 0)
    feature_list = struct.pack(">H", 0)
    # GSUB header 1.0: major(2) minor(2) scriptListOff(2) featureListOff(2) lookupListOff(2)
    header_len = 10
    script_off = header_len
    feature_off = script_off + len(script_list)
    lookup_off = feature_off + len(feature_list)
    return (
        struct.pack(">HHHHH", 1, 0, script_off, feature_off, lookup_off)
        + script_list + feature_list + lookup_list
    )


def _build_cbdt_font(
    codepoint_to_gid: dict[int, int],
    glyph_png: dict[int, bytes],
    *,
    ppem: int = 109,
    variation: tuple[int, int, int] | None = None,
    ligatures: dict[tuple[int, ...], int] | None = None,
) -> bytes:
    """Assemble a minimal OpenType CBDT font with the given cmap + glyphs.

    ``codepoint_to_gid`` seeds the cmap format-12 table. ``glyph_png`` maps
    gid -> PNG bytes for the single strike. ``variation``, if given, is
    (codepoint, selector, gid) for a cmap format-14 non-default mapping.
    Only the tables the reader touches are emitted, with correct offsets.
    """
    # --- cmap ---
    # Build format-12 groups (one per contiguous run; here one per entry).
    items = sorted(codepoint_to_gid.items())
    groups = b"".join(struct.pack(">LLL", cp, cp, gid) for cp, gid in items)
    sub12 = struct.pack(">HHLL", 12, 0, 16 + len(groups), 0) + struct.pack(">L", len(items)) + groups

    sub14 = b""
    if variation is not None:
        vcp, vsel, vgid = variation
        # one nonDefaultUVS mapping
        nondefault = struct.pack(">L", 1) + bytes([(vcp >> 16) & 0xFF, (vcp >> 8) & 0xFF, vcp & 0xFF]) + struct.pack(">H", vgid)
        # format(2) length(4) numRecords(4) then record: selector(3) defaultOff(4) nonDefaultOff(4)
        header_len = 2 + 4 + 4 + 11
        sub14 = (
            struct.pack(">H", 14)
            + struct.pack(">L", header_len + len(nondefault))
            + struct.pack(">L", 1)
            + bytes([(vsel >> 16) & 0xFF, (vsel >> 8) & 0xFF, vsel & 0xFF])
            + struct.pack(">L", 0)              # no default UVS table
            + struct.pack(">L", header_len)     # nonDefault at end of subtable
            + nondefault
        )

    # cmap header: version(2) numTables(2) then encoding records (platform(2) encoding(2) offset(4))
    n_sub = 1 + (1 if sub14 else 0)
    enc_records_len = 4 + n_sub * 8
    cmap = struct.pack(">HH", 0, n_sub)
    cmap += struct.pack(">HHL", 3, 10, enc_records_len)  # plat 3 enc 10 -> sub12
    if sub14:
        cmap += struct.pack(">HHL", 0, 5, enc_records_len + len(sub12))  # plat 0 enc 5 -> sub14
    cmap += sub12 + sub14

    # --- CBDT --- glyph records: SmallGlyphMetrics(5) + dataLen(4) + PNG
    cbdt = b"\x00\x03\x00\x00"  # version 3.0 header
    glyph_offsets: dict[int, int] = {}
    for gid in sorted(glyph_png):
        glyph_offsets[gid] = len(cbdt)
        png = glyph_png[gid]
        # height,width,bearingX,bearingY,advance
        metrics = struct.pack(">BBbbB", 128, 136, 0, 101, 136)
        cbdt += metrics + struct.pack(">L", len(png)) + png
    cbdt_end = len(cbdt)

    # --- CBLC --- one strike, one IndexSubTable (format 1, image format 17)
    gids = sorted(glyph_png)
    first_g, last_g = gids[0], gids[-1]
    # IndexSubTable format 1: header(8) + (n+1) offsets(4 each), offsets
    # relative to imageDataOffset within CBDT.
    offsets = []
    for gid in range(first_g, last_g + 1):
        offsets.append(glyph_offsets.get(gid, cbdt_end))
    offsets.append(cbdt_end)  # sentinel end offset
    index_subtable = struct.pack(">HHL", 1, 17, 0) + b"".join(struct.pack(">L", o) for o in offsets)
    # IndexSubTableArray: one record firstGlyph(2) lastGlyph(2) addOffset(4)
    ista = struct.pack(">HHL", first_g, last_g, 8)  # addOffset = past this 8-byte record
    index_block = ista + index_subtable

    # bitmapSizeTable (48 bytes): indexSubTableArrayOffset(4) indexTablesSize(4)
    # numberOfIndexSubTables(4) colorRef(4) hori(12) vert(12) startGlyph(2)
    # endGlyph(2) ppemX(1) ppemY(1) bitDepth(1) flags(1)
    cblc_header_len = 8
    ista_offset_in_cblc = cblc_header_len + 48  # array starts after header+sizeTable
    size_table = (
        struct.pack(">LLL", ista_offset_in_cblc, len(index_block), 1)
        + struct.pack(">L", 0)
        + b"\x00" * 12 + b"\x00" * 12
        + struct.pack(">HH", first_g, last_g)
        + struct.pack(">BBBB", ppem, ppem, 32, 0)
    )
    cblc = struct.pack(">HHL", 3, 0, 1) + size_table + index_block

    # --- assemble sfnt ---
    tables = {"cmap": cmap, "CBLC": cblc, "CBDT": cbdt}
    if ligatures:
        tables["GSUB"] = _build_gsub_ligatures(ligatures)
    tags = sorted(tables)
    num = len(tags)
    header = struct.pack(">4sHHHH", b"\x00\x01\x00\x00", num, 0, 0, 0)
    dir_len = num * 16
    body = b""
    records = b""
    offset = 12 + dir_len
    for tag in tags:
        tbl = tables[tag]
        records += struct.pack(">4sLLL", tag.encode("latin1"), 0, offset, len(tbl))
        body += tbl
        # pad to 4-byte boundary
        pad = (-len(tbl)) % 4
        body += b"\x00" * pad
        offset += len(tbl) + pad
    return header + records + body


# --- Tests ----------------------------------------------------------------


def _font(*args, **kwargs) -> EmojiFont:
    """Build a synthetic font and wrap it in the reader under test."""
    return EmojiFont(_build_cbdt_font(*args, **kwargs))


def test_table_directory_parsed():
    font = _font({0x1F680: 1}, {1: _tiny_png()})
    assert set(font.tables) == {"cmap", "CBLC", "CBDT"}


def test_glyph_id_lookup():
    font = _font({0x1F680: 7, 0x2705: 3}, {3: _tiny_png(), 7: _tiny_png()})
    assert font.glyph_id(0x1F680) == 7
    assert font.glyph_id(0x2705) == 3


def test_glyph_id_absent_returns_zero():
    font = _font({0x1F680: 1}, {1: _tiny_png()})
    assert font.glyph_id(0x0041) == 0  # 'A' not in the font


def test_glyph_id_binary_search_many_entries():
    cps = {0x1F600 + i: i + 1 for i in range(50)}
    pngs = {i + 1: _tiny_png() for i in range(50)}
    font = _font(cps, pngs)
    # spot-check across the sorted range
    assert font.glyph_id(0x1F600) == 1
    assert font.glyph_id(0x1F600 + 25) == 26
    assert font.glyph_id(0x1F600 + 49) == 50
    assert font.glyph_id(0x1F600 + 50) == 0


def test_bitmap_extraction_returns_valid_png():
    png = _tiny_png(w=10, h=6)
    font = _font({0x1F680: 1}, {1: png})
    bmp = font.glyph_bitmap(1)
    assert bmp is not None
    assert bmp.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert bmp.png == png
    assert bmp.advance == 136
    assert bmp.bearing_y == 101
    assert bmp.ppem == 109


def test_bitmap_cached():
    font = _font({0x1F680: 1}, {1: _tiny_png()})
    a = font.glyph_bitmap(1)
    b = font.glyph_bitmap(1)
    assert a is b


def test_notdef_glyph_returns_none():
    font = _font({0x1F680: 1}, {1: _tiny_png()})
    assert font.glyph_bitmap(0) is None


def test_absent_gid_returns_none():
    font = _font({0x1F680: 1}, {1: _tiny_png()})
    assert font.glyph_bitmap(999) is None


def test_variation_selector_lookup():
    font = _font(
        {0x2764: 5}, {5: _tiny_png()}, variation=(0x2764, 0xFE0F, 5)
    )
    assert font.variation_glyph_id(0x2764, 0xFE0F) == 5
    # An unmapped selector returns None (caller falls back to glyph_id).
    assert font.variation_glyph_id(0x2764, 0xFE0E) is None


def test_variation_lookup_without_format14_returns_none():
    font = _font({0x2764: 5}, {5: _tiny_png()})  # no variation table
    assert font.variation_glyph_id(0x2764, 0xFE0F) is None


@pytest.mark.parametrize("blob", [
    b"",
    b"\x00\x01",
    b"XXXX" + b"\x00" * 20,
    b"\x00\x01\x00\x00" + b"\x00\x05" + b"\x00" * 6,  # claims 5 tables, truncated
])
def test_malformed_font_raises_emojifonterror(blob):
    font = EmojiFont(blob)
    with pytest.raises(EmojiFontError):
        font.tables
        font.glyph_id(0x1F680)


def test_font_without_cmap12_raises_on_lookup():
    # Build a font then corrupt: easiest is a font with only CBLC/CBDT.
    font = _font({0x1F680: 1}, {1: _tiny_png()})
    # Remove cmap from the parsed table map to simulate absence.
    font._tables = {k: v for k, v in font.tables.items() if k != "cmap"}
    font._cmap_parsed = False
    with pytest.raises(EmojiFontError):
        font.glyph_id(0x1F680)


# --- Optional smoke test against a real system Noto Color Emoji -----------
# Skipped when the font isn't installed; guards against the synthetic
# fixture diverging from a real-world CBDT font (big metrics, index format 2,
# format-12 binary search over thousands of groups, etc.).

import glob
import os


def _find_system_noto() -> str | None:
    candidates = []
    candidates += glob.glob("/usr/share/fonts/**/NotoColorEmoji.ttf", recursive=True)
    candidates += glob.glob(
        "/home/.steamos/offload/var/lib/flatpak/**/NotoColorEmoji.ttf", recursive=True
    )
    candidates += glob.glob(
        os.path.expanduser("~/.fonts/**/NotoColorEmoji.ttf"), recursive=True
    )
    return candidates[0] if candidates else None


def test_real_noto_color_emoji_smoke():
    path = _find_system_noto()
    if path is None:
        pytest.skip("system NotoColorEmoji.ttf not found")
    font = EmojiFont(open(path, "rb").read())
    assert "CBDT" in font.tables and "CBLC" in font.tables
    rocket = font.glyph_id(0x1F680)
    assert rocket != 0
    bmp = font.glyph_bitmap(rocket)
    assert bmp is not None
    assert bmp.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert bmp.width > 0 and bmp.height > 0
    # A few more common emoji resolve and extract.
    for cp in (0x2705, 0x26A0, 0x1F44D, 0x1F600):
        gid = font.glyph_id(cp)
        assert gid != 0
        assert font.glyph_bitmap(gid) is not None


# --- GSUB ligature parsing (Phase 4) --------------------------------------


def test_gsub_ligatures_parsed():
    ligs = {(1, 2): 100, (1, 2, 3): 101, (4, 5): 102}
    font = _font(
        {0x1F468: 1, 0x200D: 2, 0x1F469: 3, 0x1F1EF: 4, 0x1F1F5: 5},
        {g: _tiny_png() for g in range(1, 103)},
        ligatures=ligs,
    )
    assert font.lookup_ligature((1, 2)) == 100
    assert font.lookup_ligature((1, 2, 3)) == 101
    assert font.lookup_ligature((4, 5)) == 102


def test_gsub_max_ligature_length():
    font = _font(
        {0x1F468: 1, 0x1F469: 2, 0x1F467: 3},
        {1: _tiny_png(), 2: _tiny_png(), 3: _tiny_png(), 9: _tiny_png()},
        ligatures={(1, 2, 3): 9},
    )
    assert font.max_ligature_length == 3


def test_gsub_absent_ligature_returns_none():
    font = _font({0x1F680: 1}, {1: _tiny_png(), 9: _tiny_png()}, ligatures={(1, 1): 9})
    assert font.lookup_ligature((1, 2, 3)) is None


def test_no_gsub_table_means_no_ligatures():
    font = _font({0x1F680: 1}, {1: _tiny_png()})  # no ligatures arg -> no GSUB
    assert font.max_ligature_length == 0
    assert font.lookup_ligature((1, 2)) is None
