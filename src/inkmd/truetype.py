"""Hand-rolled OpenType/TrueType outline reader (``glyf``-flavoured fonts).

This is the data-layer foundation of inkmd's font-embedding path (Spine 1).
Given raw font bytes it parses just enough OpenType to:

* map a Unicode codepoint to a glyph id (``cmap`` formats 4 and 12),
* read a glyph's horizontal advance width (``hhea`` + ``hmtx``),
* read a glyph's outline as contours of ``(x, y, on_curve)`` points
  (``head`` + ``maxp`` + ``loca`` + ``glyf``), resolving composite glyphs
  into their components with the component offset/transform applied.

It emits no PDF and touches no measurement or rendering code; downstream
streams (S2 measurement, S3 emission) consume what this produces.

Only TrueType-outline flavours are in scope: sfnt tags ``\\x00\\x01\\x00\\x00``
and ``true``. CFF outlines (``OTTO``) are explicitly out of scope and raise
:class:`TrueTypeFontError` rather than being half-parsed.

Everything is parsed lazily and cached. Any structural problem (truncation,
a missing required table, an unsupported flavour) raises
:class:`TrueTypeFontError` so a caller can fall back cleanly rather than
leak a ``struct.error``/``IndexError`` from a malformed or hostile font.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


class TrueTypeFontError(Exception):
    """Raised when a TrueType font can't be parsed or lacks a needed table.

    Mirrors ``EmojiFontError``: a font reader is an attack surface, so a
    truncated or malformed table fails with this typed error instead of a
    raw ``struct.error`` / ``IndexError`` leaking to the caller.
    """


@dataclass(frozen=True)
class GlyphPoint:
    """A single outline point: design-unit coordinates + on/off-curve flag.

    ``on_curve`` is True for on-curve points and False for off-curve
    (quadratic Bezier control) points. Coordinates are integers in font
    design units (``units_per_em``).
    """

    x: int
    y: int
    on_curve: bool


# A contour is an ordered list of points; a glyph outline is a list of
# contours. Empty glyphs (e.g. space) have an empty list.
Contour = list[GlyphPoint]


# Composite component flags (OpenType ``glyf`` composite spec).
_ARG_1_AND_2_ARE_WORDS = 0x0001
_ARGS_ARE_XY_VALUES = 0x0002
_WE_HAVE_A_SCALE = 0x0008
_MORE_COMPONENTS = 0x0020
_WE_HAVE_AN_X_AND_Y_SCALE = 0x0040
_WE_HAVE_A_TWO_BY_TWO = 0x0080

# Simple-glyph coordinate flags.
_ON_CURVE = 0x01
_X_SHORT = 0x02
_Y_SHORT = 0x04
_REPEAT = 0x08
_X_SAME_OR_POSITIVE = 0x10
_Y_SAME_OR_POSITIVE = 0x20

# Guard against pathological/maliciously-deep composite recursion.
_MAX_COMPOSITE_DEPTH = 8


class TrueTypeFont:
    """Lazy reader over a ``glyf``-flavoured OpenType/TrueType font.

    Construct from the raw font bytes. Each table is parsed on first use and
    cached. The public surface S2/S3 build on:

    * :attr:`units_per_em` - font design units per em (from ``head``).
    * :attr:`num_glyphs` - glyph count (from ``maxp``).
    * :attr:`tables` - ``tag -> (offset, length)`` table directory.
    * :meth:`glyph_id` - codepoint -> glyph id (0/.notdef if absent).
    * :meth:`advance_width` - glyph id -> advance width in design units.
    * :meth:`glyph_outline` - glyph id -> list of contours, composites
      resolved into concrete points.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._tables: dict[str, tuple[int, int]] | None = None
        # head-derived scalars.
        self._units_per_em: int | None = None
        self._index_to_loc: int | None = None
        # maxp / hhea scalars.
        self._num_glyphs: int | None = None
        self._num_h_metrics: int | None = None
        # loca offsets (length numGlyphs+1, absolute offsets within glyf).
        self._loca: list[int] | None = None
        # cmap subtable absolute offsets, resolved lazily.
        self._cmap4_off: int | None = None
        self._cmap12_off: int | None = None
        self._cmap_parsed = False
        # gid -> resolved contour list cache.
        self._outline_cache: dict[int, list[Contour]] = {}

    # --- Table directory --------------------------------------------------

    @property
    def tables(self) -> dict[str, tuple[int, int]]:
        """Map of table tag -> (offset, length), parsed once."""
        if self._tables is None:
            self._tables = self._parse_table_directory()
        return self._tables

    def _parse_table_directory(self) -> dict[str, tuple[int, int]]:
        # Adapted from emoji_font._parse_table_directory: same sfnt header
        # shape, but here we reject OTTO outright (CFF is out of S1 scope)
        # and accept only the TrueType-outline flavours.
        data = self._data
        if len(data) < 12:
            raise TrueTypeFontError("font too short for an sfnt header")
        sfnt_tag = data[0:4]
        if sfnt_tag == b"OTTO":
            raise TrueTypeFontError(
                "CFF outlines (OTTO) not supported; need a glyf-flavoured font"
            )
        if sfnt_tag == b"ttcf":
            raise TrueTypeFontError("TrueType collections (ttcf) not supported")
        if sfnt_tag not in (b"\x00\x01\x00\x00", b"true"):
            raise TrueTypeFontError(f"unsupported sfnt tag {sfnt_tag!r}")
        num_tables = struct.unpack(">H", data[4:6])[0]
        tables: dict[str, tuple[int, int]] = {}
        off = 12
        for _ in range(num_tables):
            if off + 16 > len(data):
                raise TrueTypeFontError("truncated table directory")
            tag = data[off:off + 4]
            t_off, t_len = struct.unpack(">LL", data[off + 8:off + 16])
            tables[tag.decode("latin1")] = (t_off, t_len)
            off += 16
        return tables

    def _table(self, tag: str) -> tuple[int, int]:
        try:
            return self.tables[tag]
        except KeyError:
            raise TrueTypeFontError(f"font has no {tag!r} table") from None

    def _table_bytes(self, tag: str) -> tuple[int, int]:
        """Return (offset, length) for ``tag`` after bounds-checking that the
        whole table lies inside the font."""
        off, length = self._table(tag)
        if off < 0 or length < 0 or off + length > len(self._data):
            raise TrueTypeFontError(f"{tag!r} table out of bounds")
        return off, length

    # --- head / maxp / hhea ----------------------------------------------

    def _ensure_head(self) -> None:
        if self._units_per_em is not None:
            return
        data = self._data
        off, length = self._table("head")
        # Need unitsPerEm (uint16 @ +18) and indexToLocFormat (int16 @ +50).
        if length < 54 or off + 54 > len(data):
            raise TrueTypeFontError("truncated head table")
        self._units_per_em = struct.unpack(">H", data[off + 18:off + 20])[0]
        self._index_to_loc = struct.unpack(">h", data[off + 50:off + 52])[0]
        if self._index_to_loc not in (0, 1):
            raise TrueTypeFontError(
                f"invalid indexToLocFormat {self._index_to_loc}"
            )
        if self._units_per_em == 0:
            raise TrueTypeFontError("head unitsPerEm is zero")

    @property
    def units_per_em(self) -> int:
        """Font design units per em (from ``head``)."""
        self._ensure_head()
        assert self._units_per_em is not None
        return self._units_per_em

    def _ensure_maxp(self) -> None:
        if self._num_glyphs is not None:
            return
        data = self._data
        off, length = self._table("maxp")
        if length < 6 or off + 6 > len(data):
            raise TrueTypeFontError("truncated maxp table")
        self._num_glyphs = struct.unpack(">H", data[off + 4:off + 6])[0]

    @property
    def num_glyphs(self) -> int:
        """Number of glyphs in the font (from ``maxp``)."""
        self._ensure_maxp()
        assert self._num_glyphs is not None
        return self._num_glyphs

    def _ensure_hhea(self) -> None:
        if self._num_h_metrics is not None:
            return
        data = self._data
        off, length = self._table("hhea")
        # numberOfHMetrics is uint16 @ +34 (last field of the 36-byte table).
        if length < 36 or off + 36 > len(data):
            raise TrueTypeFontError("truncated hhea table")
        self._num_h_metrics = struct.unpack(">H", data[off + 34:off + 36])[0]
        if self._num_h_metrics == 0:
            raise TrueTypeFontError("hhea numberOfHMetrics is zero")

    # --- hmtx -------------------------------------------------------------

    def advance_width(self, gid: int) -> int:
        """Return glyph ``gid``'s horizontal advance width in design units.

        The first ``numberOfHMetrics`` glyphs carry an explicit advance; any
        glyph beyond that reuses the last explicit advance (the monospaced
        tail that ``hmtx`` omits). Out-of-range gids raise.
        """
        self._ensure_hhea()
        self._ensure_maxp()
        assert self._num_h_metrics is not None and self._num_glyphs is not None
        if gid < 0 or gid >= self._num_glyphs:
            raise TrueTypeFontError(f"glyph id {gid} out of range")
        data = self._data
        off, length = self._table_bytes("hmtx")
        # Clamp to the last explicit metric for the reused-advance tail.
        idx = gid if gid < self._num_h_metrics else self._num_h_metrics - 1
        entry = off + idx * 4
        if entry + 2 > off + length or entry + 2 > len(data):
            raise TrueTypeFontError("truncated hmtx table")
        return struct.unpack(">H", data[entry:entry + 2])[0]

    # --- loca -------------------------------------------------------------

    def _ensure_loca(self) -> list[int]:
        if self._loca is not None:
            return self._loca
        self._ensure_head()
        self._ensure_maxp()
        assert self._index_to_loc is not None and self._num_glyphs is not None
        data = self._data
        off, length = self._table_bytes("loca")
        n = self._num_glyphs + 1
        loca: list[int] = []
        if self._index_to_loc == 0:
            # Short format: uint16 offsets, each the true offset / 2.
            if off + n * 2 > off + length or off + n * 2 > len(data):
                raise TrueTypeFontError("truncated short loca table")
            for i in range(n):
                v = struct.unpack(">H", data[off + i * 2:off + i * 2 + 2])[0]
                loca.append(v * 2)
        else:
            # Long format: uint32 offsets, true offsets.
            if off + n * 4 > off + length or off + n * 4 > len(data):
                raise TrueTypeFontError("truncated long loca table")
            for i in range(n):
                v = struct.unpack(">L", data[off + i * 4:off + i * 4 + 4])[0]
                loca.append(v)
        self._loca = loca
        return loca

    # --- glyf -------------------------------------------------------------

    def glyph_outline(self, gid: int) -> list[Contour]:
        """Return glyph ``gid``'s outline as a list of contours.

        Each contour is a list of :class:`GlyphPoint`. Composite glyphs are
        resolved into their components' points with the component
        offset/transform applied. An empty glyph (e.g. space, ``loca`` length
        0) yields an empty contour list. Coordinates are font design units.
        """
        if gid in self._outline_cache:
            return self._outline_cache[gid]
        result = self._read_glyph(gid, 0)
        self._outline_cache[gid] = result
        return result

    def _glyf_glyph_bytes(self, gid: int) -> bytes | None:
        """Return the raw glyf bytes for ``gid``, or None for an empty glyph."""
        self._ensure_maxp()
        assert self._num_glyphs is not None
        if gid < 0 or gid >= self._num_glyphs:
            raise TrueTypeFontError(f"glyph id {gid} out of range")
        loca = self._ensure_loca()
        glyf_off, glyf_len = self._table_bytes("glyf")
        start, end = loca[gid], loca[gid + 1]
        if end < start:
            raise TrueTypeFontError("loca offsets not monotonic")
        if start == end:
            return None  # empty glyph (no outline, e.g. space)
        if glyf_off + end > glyf_off + glyf_len or glyf_off + end > len(self._data):
            raise TrueTypeFontError("glyph extends past glyf table")
        return self._data[glyf_off + start:glyf_off + end]

    def _read_glyph(self, gid: int, depth: int) -> list[Contour]:
        if depth > _MAX_COMPOSITE_DEPTH:
            raise TrueTypeFontError("composite glyph recursion too deep")
        blob = self._glyf_glyph_bytes(gid)
        if blob is None:
            return []
        if len(blob) < 10:
            raise TrueTypeFontError("truncated glyph header")
        num_contours = struct.unpack(">h", blob[0:2])[0]
        if num_contours >= 0:
            return self._parse_simple_glyph(blob, num_contours)
        return self._parse_composite_glyph(blob, depth)

    def _parse_simple_glyph(
        self, blob: bytes, num_contours: int
    ) -> list[Contour]:
        # Glyph header is 10 bytes (numberOfContours + bbox); skip it.
        pos = 10
        if pos + num_contours * 2 > len(blob):
            raise TrueTypeFontError("truncated endPtsOfContours")
        end_pts: list[int] = []
        for _ in range(num_contours):
            end_pts.append(struct.unpack(">H", blob[pos:pos + 2])[0])
            pos += 2
        if num_contours == 0:
            return []
        num_points = end_pts[-1] + 1

        # instructionLength + instructions (skip the bytes).
        if pos + 2 > len(blob):
            raise TrueTypeFontError("truncated instructionLength")
        instr_len = struct.unpack(">H", blob[pos:pos + 2])[0]
        pos += 2 + instr_len
        if pos > len(blob):
            raise TrueTypeFontError("truncated glyph instructions")

        # Flags array, with repeat-flag expansion.
        flags: list[int] = []
        while len(flags) < num_points:
            if pos >= len(blob):
                raise TrueTypeFontError("truncated glyph flags")
            flag = blob[pos]
            pos += 1
            flags.append(flag)
            if flag & _REPEAT:
                if pos >= len(blob):
                    raise TrueTypeFontError("truncated repeat count")
                repeat = blob[pos]
                pos += 1
                flags.extend([flag] * repeat)
        if len(flags) > num_points:
            # A trailing repeat may overshoot; the spec forbids it, treat as
            # malformed rather than silently truncate.
            raise TrueTypeFontError("glyph flags overflow point count")

        # X coordinates: delta-encoded, short/same/sign rules.
        xs: list[int] = []
        x = 0
        for flag in flags:
            if flag & _X_SHORT:
                if pos >= len(blob):
                    raise TrueTypeFontError("truncated x coordinates")
                dx = blob[pos]
                pos += 1
                x += dx if (flag & _X_SAME_OR_POSITIVE) else -dx
            else:
                if not (flag & _X_SAME_OR_POSITIVE):
                    if pos + 2 > len(blob):
                        raise TrueTypeFontError("truncated x coordinates")
                    x += struct.unpack(">h", blob[pos:pos + 2])[0]
                    pos += 2
                # else: same as previous, x unchanged.
            xs.append(x)

        # Y coordinates: same rules with the Y flags.
        ys: list[int] = []
        y = 0
        for flag in flags:
            if flag & _Y_SHORT:
                if pos >= len(blob):
                    raise TrueTypeFontError("truncated y coordinates")
                dy = blob[pos]
                pos += 1
                y += dy if (flag & _Y_SAME_OR_POSITIVE) else -dy
            else:
                if not (flag & _Y_SAME_OR_POSITIVE):
                    if pos + 2 > len(blob):
                        raise TrueTypeFontError("truncated y coordinates")
                    y += struct.unpack(">h", blob[pos:pos + 2])[0]
                    pos += 2
            ys.append(y)

        # Slice the flat point list into contours by endPtsOfContours.
        contours: list[Contour] = []
        start = 0
        for end in end_pts:
            if end < start or end >= num_points:
                raise TrueTypeFontError("invalid endPtsOfContours value")
            contour: Contour = [
                GlyphPoint(xs[i], ys[i], bool(flags[i] & _ON_CURVE))
                for i in range(start, end + 1)
            ]
            contours.append(contour)
            start = end + 1
        return contours

    def _parse_composite_glyph(self, blob: bytes, depth: int) -> list[Contour]:
        pos = 10  # skip glyph header (numberOfContours + bbox)
        contours: list[Contour] = []
        while True:
            if pos + 4 > len(blob):
                raise TrueTypeFontError("truncated composite component")
            flags, glyph_index = struct.unpack(">HH", blob[pos:pos + 4])
            pos += 4

            # Component arguments: words or bytes, xy values or point indices.
            if flags & _ARG_1_AND_2_ARE_WORDS:
                if pos + 4 > len(blob):
                    raise TrueTypeFontError("truncated composite args")
                if flags & _ARGS_ARE_XY_VALUES:
                    arg1, arg2 = struct.unpack(">hh", blob[pos:pos + 4])
                else:
                    arg1, arg2 = struct.unpack(">HH", blob[pos:pos + 4])
                pos += 4
            else:
                if pos + 2 > len(blob):
                    raise TrueTypeFontError("truncated composite args")
                if flags & _ARGS_ARE_XY_VALUES:
                    arg1, arg2 = struct.unpack(">bb", blob[pos:pos + 2])
                else:
                    arg1, arg2 = struct.unpack(">BB", blob[pos:pos + 2])
                pos += 2

            # Optional transform. F2Dot14 fixed-point read as exact integers;
            # the /16384.0 scaling happens here only for measurement-side
            # coordinate computation. S1 emits no bytes, so this float never
            # becomes a dict key, hash, or emitted value (see brief's
            # determinism rule).
            a = d = 1.0
            b = c = 0.0
            if flags & _WE_HAVE_A_SCALE:
                if pos + 2 > len(blob):
                    raise TrueTypeFontError("truncated composite scale")
                a = d = _f2dot14(blob[pos:pos + 2])
                pos += 2
            elif flags & _WE_HAVE_AN_X_AND_Y_SCALE:
                if pos + 4 > len(blob):
                    raise TrueTypeFontError("truncated composite x/y scale")
                a = _f2dot14(blob[pos:pos + 2])
                d = _f2dot14(blob[pos + 2:pos + 4])
                pos += 4
            elif flags & _WE_HAVE_A_TWO_BY_TWO:
                if pos + 8 > len(blob):
                    raise TrueTypeFontError("truncated composite 2x2")
                a = _f2dot14(blob[pos:pos + 2])
                b = _f2dot14(blob[pos + 2:pos + 4])
                c = _f2dot14(blob[pos + 4:pos + 6])
                d = _f2dot14(blob[pos + 6:pos + 8])
                pos += 8

            # ARGS_ARE_XY_VALUES: arg1/arg2 are a translation in design units.
            # Point-matching composites (the flag clear) are rare in text
            # fonts and not needed for S2 measurement; leave an honest gap.
            if flags & _ARGS_ARE_XY_VALUES:
                dx, dy = arg1, arg2
            else:
                raise NotImplementedError(
                    "composite point-matching (ARGS_ARE_XY_VALUES clear) "
                    "is not supported; no text-font glyph in v0.4 scope needs "
                    "it. Add point-index alignment here if a real font does."
                )

            component = self._read_glyph(glyph_index, depth + 1)
            for contour in component:
                transformed: Contour = []
                for p in contour:
                    nx = round(a * p.x + c * p.y) + dx
                    ny = round(b * p.x + d * p.y) + dy
                    transformed.append(GlyphPoint(nx, ny, p.on_curve))
                contours.append(transformed)

            if not (flags & _MORE_COMPONENTS):
                break
        return contours

    # --- cmap -------------------------------------------------------------

    def _ensure_cmap(self) -> None:
        if self._cmap_parsed:
            return
        data = self._data
        cmap_off, _ = self._table_bytes("cmap")
        if cmap_off + 4 > len(data):
            raise TrueTypeFontError("truncated cmap header")
        n_sub = struct.unpack(">H", data[cmap_off + 2:cmap_off + 4])[0]
        # Record preferred subtables. Selection priority (brief): a
        # format-12 (3,10)/(0,4)/(0,6) full-range subtable beats a format-4
        # (3,1)/(0,3) BMP subtable. We record the first of each format we
        # see and prefer format-12 at lookup time.
        for i in range(n_sub):
            rec = cmap_off + 4 + i * 8
            if rec + 8 > len(data):
                raise TrueTypeFontError("truncated cmap subtable record")
            sub_off = struct.unpack(">L", data[rec + 4:rec + 8])[0]
            abs_off = cmap_off + sub_off
            if abs_off + 2 > len(data):
                continue
            fmt = struct.unpack(">H", data[abs_off:abs_off + 2])[0]
            if fmt == 12 and self._cmap12_off is None:
                self._cmap12_off = abs_off
            elif fmt == 4 and self._cmap4_off is None:
                self._cmap4_off = abs_off
        if self._cmap12_off is None and self._cmap4_off is None:
            raise TrueTypeFontError(
                "font has no usable cmap subtable (need format 4 or 12)"
            )
        self._cmap_parsed = True

    def glyph_id(self, codepoint: int) -> int:
        """Return the glyph id for ``codepoint``, or 0 (.notdef) if absent.

        Prefers a format-12 (full-range) subtable; falls back to format-4
        (BMP). A codepoint with no mapping resolves to 0.
        """
        self._ensure_cmap()
        if self._cmap12_off is not None:
            gid = self._cmap12_lookup(codepoint)
            if gid != 0 or self._cmap4_off is None:
                return gid
        if self._cmap4_off is not None:
            return self._cmap4_lookup(codepoint)
        return 0

    def _cmap12_lookup(self, cp: int) -> int:
        # Lifted from emoji_font._cmap12_lookup (binary search over sorted
        # segmented-coverage groups); behaviour identical.
        data = self._data
        o = self._cmap12_off
        assert o is not None
        if o + 16 > len(data):
            raise TrueTypeFontError("truncated cmap format-12 header")
        n_groups = struct.unpack(">L", data[o + 12:o + 16])[0]
        base = o + 16
        if base + n_groups * 12 > len(data):
            raise TrueTypeFontError("truncated cmap format-12 groups")
        lo, hi = 0, n_groups - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            g = base + mid * 12
            start, end, start_gid = struct.unpack(">LLL", data[g:g + 12])
            if cp < start:
                hi = mid - 1
            elif cp > end:
                lo = mid + 1
            else:
                return start_gid + (cp - start)
        return 0

    def _cmap4_lookup(self, cp: int) -> int:
        # format-4 (BMP segment mapping) is genuinely new vs emoji_font.
        # Layout: format(2) length(2) language(2) segCountX2(2)
        # searchRange(2) entrySelector(2) rangeShift(2) then parallel arrays
        # endCode[segCount], reservedPad(2), startCode[segCount],
        # idDelta[segCount], idRangeOffset[segCount], then the glyphIdArray.
        if cp > 0xFFFF:
            return 0  # format 4 only covers the BMP
        data = self._data
        o = self._cmap4_off
        assert o is not None
        if o + 14 > len(data):
            raise TrueTypeFontError("truncated cmap format-4 header")
        seg_x2 = struct.unpack(">H", data[o + 6:o + 8])[0]
        seg_count = seg_x2 // 2
        if seg_count == 0:
            return 0
        end_base = o + 14
        start_base = end_base + seg_x2 + 2  # +2 for reservedPad
        delta_base = start_base + seg_x2
        range_base = delta_base + seg_x2
        if range_base + seg_x2 > len(data):
            raise TrueTypeFontError("truncated cmap format-4 arrays")
        for s in range(seg_count):
            end_code = struct.unpack(">H", data[end_base + s * 2:end_base + s * 2 + 2])[0]
            if cp > end_code:
                continue
            start_code = struct.unpack(
                ">H", data[start_base + s * 2:start_base + s * 2 + 2]
            )[0]
            if cp < start_code:
                return 0  # falls in a gap before this segment
            id_delta = struct.unpack(
                ">h", data[delta_base + s * 2:delta_base + s * 2 + 2]
            )[0]
            id_range_off = struct.unpack(
                ">H", data[range_base + s * 2:range_base + s * 2 + 2]
            )[0]
            if id_range_off == 0:
                return (cp + id_delta) & 0xFFFF
            # idRangeOffset indexes into glyphIdArray relative to its own slot.
            gi_addr = range_base + s * 2 + id_range_off + (cp - start_code) * 2
            if gi_addr + 2 > len(data):
                raise TrueTypeFontError("cmap format-4 glyphIdArray out of bounds")
            gid = struct.unpack(">H", data[gi_addr:gi_addr + 2])[0]
            if gid == 0:
                return 0
            return (gid + id_delta) & 0xFFFF
        return 0


def _f2dot14(b: bytes) -> float:
    """Decode a 2-byte F2Dot14 fixed-point value to float.

    Used only for composite-component transforms, which feed measurement-side
    coordinate computation. S1 emits no bytes, so this float never becomes a
    dict key / hash / emitted value (the determinism rule's concern).
    """
    raw = struct.unpack(">h", b)[0]
    return raw / 16384.0
