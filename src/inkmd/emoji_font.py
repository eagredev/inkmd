"""Hand-rolled OpenType reader for color-emoji glyph extraction.

inkmd renders color emoji by extracting the per-glyph bitmaps embedded in
a CBDT/CBLC color font (e.g. Noto Color Emoji) and placing them as PDF
image XObjects (reusing the indexed-PNG + soft-mask path in ``pdf.py``).

This module parses just enough OpenType to do that, with no third-party
dependencies:

* the table directory,
* ``cmap`` formats 12 (32-bit codepoint -> glyph id) and 14 (Unicode
  variation sequences, for the emoji/text presentation selectors
  U+FE0F / U+FE0E),
* the ``CBLC``/``CBDT`` bitmap location + data tables, to pull a glyph's
  embedded PNG verbatim,
* ``GSUB`` type-4 ligature lookups (parsed in a later phase) for
  multi-codepoint emoji sequences.

Everything is parsed lazily and cached. Any structural problem raises
:class:`EmojiFontError` so the caller can fall back to a textual
representation rather than crash a compile.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


class EmojiFontError(Exception):
    """Raised when an emoji font can't be parsed or lacks a needed glyph.

    Callers catch this to fall back to the configured emoji fallback
    (textual name or drop) instead of failing the compile.
    """


@dataclass(frozen=True)
class GlyphBitmap:
    """An extracted color-glyph bitmap and its placement metrics.

    ``png`` is the glyph's embedded image, valid PNG bytes ready to embed
    as an XObject. ``width``/``height`` are its pixel dimensions. The
    metrics are in font pixels at the strike's ppem (``ppem``):
    ``bearing_x``/``bearing_y`` locate the top-left of the bitmap relative
    to the pen origin/baseline, and ``advance`` is the horizontal advance.
    """
    png: bytes
    width: int
    height: int
    bearing_x: int
    bearing_y: int
    advance: int
    ppem: int


class EmojiFont:
    """Lazy reader over an OpenType CBDT/CBLC color-emoji font.

    Construct from the raw font bytes. Parsing of each table is deferred
    until first use and cached. Use :meth:`glyph_id` to map a codepoint to
    a glyph id and :meth:`glyph_bitmap` to extract that glyph's bitmap.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._tables: dict[str, tuple[int, int]] | None = None
        # cmap subtable absolute offsets, resolved lazily.
        self._cmap12_off: int | None = None
        self._cmap14_off: int | None = None
        self._cmap_parsed = False
        # CBLC strikes, parsed lazily.
        self._strikes: list[_Strike] | None = None
        # gid -> GlyphBitmap cache.
        self._bitmap_cache: dict[int, GlyphBitmap | None] = {}
        # GSUB ligature map: tuple(component gids) -> ligature gid, lazy.
        self._ligatures: dict[tuple[int, ...], int] | None = None
        self._max_ligature_len = 0

    # --- Table directory --------------------------------------------------

    @property
    def tables(self) -> dict[str, tuple[int, int]]:
        """Map of table tag -> (offset, length), parsed once."""
        if self._tables is None:
            self._tables = self._parse_table_directory()
        return self._tables

    def _parse_table_directory(self) -> dict[str, tuple[int, int]]:
        data = self._data
        if len(data) < 12:
            raise EmojiFontError("font too short for an sfnt header")
        sfnt_tag = data[0:4]
        # 0x00010000 (TrueType) or 'OTTO' (CFF). CBDT fonts are TrueType-
        # flavoured (sfnt 0x00010000); 'ttcf' collections aren't supported.
        if sfnt_tag not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
            raise EmojiFontError(f"unsupported sfnt tag {sfnt_tag!r}")
        num_tables = struct.unpack(">H", data[4:6])[0]
        tables: dict[str, tuple[int, int]] = {}
        off = 12
        for _ in range(num_tables):
            if off + 16 > len(data):
                raise EmojiFontError("truncated table directory")
            tag = data[off:off + 4]
            t_off, t_len = struct.unpack(">LL", data[off + 8:off + 16])
            tables[tag.decode("latin1")] = (t_off, t_len)
            off += 16
        return tables

    def _table(self, tag: str) -> tuple[int, int]:
        try:
            return self.tables[tag]
        except KeyError:
            raise EmojiFontError(f"font has no {tag!r} table") from None

    # --- cmap -------------------------------------------------------------

    def _ensure_cmap(self) -> None:
        if self._cmap_parsed:
            return
        data = self._data
        cmap_off, _ = self._table("cmap")
        if cmap_off + 4 > len(data):
            raise EmojiFontError("truncated cmap header")
        n_sub = struct.unpack(">H", data[cmap_off + 2:cmap_off + 4])[0]
        for i in range(n_sub):
            rec = cmap_off + 4 + i * 8
            if rec + 8 > len(data):
                raise EmojiFontError("truncated cmap subtable record")
            sub_off = struct.unpack(">L", data[rec + 4:rec + 8])[0]
            abs_off = cmap_off + sub_off
            if abs_off + 2 > len(data):
                continue
            fmt = struct.unpack(">H", data[abs_off:abs_off + 2])[0]
            if fmt == 12 and self._cmap12_off is None:
                self._cmap12_off = abs_off
            elif fmt == 14 and self._cmap14_off is None:
                self._cmap14_off = abs_off
        if self._cmap12_off is None:
            raise EmojiFontError("font has no cmap format-12 subtable")
        self._cmap_parsed = True

    def glyph_id(self, codepoint: int) -> int:
        """Return the glyph id for ``codepoint``, or 0 (.notdef) if absent.

        Uses the format-12 (segmented coverage) subtable, which covers the
        full Unicode range emoji live in.
        """
        self._ensure_cmap()
        return self._cmap12_lookup(codepoint)

    def _cmap12_lookup(self, cp: int) -> int:
        data = self._data
        o = self._cmap12_off
        assert o is not None
        n_groups = struct.unpack(">L", data[o + 12:o + 16])[0]
        # Groups are sorted by startCharCode; binary-search them.
        lo, hi = 0, n_groups - 1
        base = o + 16
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

    def variation_glyph_id(self, codepoint: int, selector: int) -> int | None:
        """Resolve a codepoint + variation selector via the cmap format-14
        subtable. Returns the glyph id, or None if the sequence isn't in
        the font's variation table (the caller should then fall back to the
        plain :meth:`glyph_id`). Returns None if there's no format-14
        subtable at all.
        """
        self._ensure_cmap()
        if self._cmap14_off is None:
            return None
        data = self._data
        o = self._cmap14_off
        # format(2) length(4) numVarSelectorRecords(4); records are
        # varSelector(3) defaultUVSOffset(4) nonDefaultUVSOffset(4).
        n_records = struct.unpack(">L", data[o + 6:o + 10])[0]
        rec = o + 10
        for _ in range(n_records):
            vs = (data[rec] << 16) | (data[rec + 1] << 8) | data[rec + 2]
            default_off, nondefault_off = struct.unpack(">LL", data[rec + 3:rec + 11])
            rec += 11
            if vs != selector:
                continue
            # Non-default UVS table maps the codepoint directly to a gid.
            if nondefault_off:
                t = o + nondefault_off
                n_mappings = struct.unpack(">L", data[t:t + 4])[0]
                m = t + 4
                for _ in range(n_mappings):
                    uni = (data[m] << 16) | (data[m + 1] << 8) | data[m + 2]
                    gid = struct.unpack(">H", data[m + 3:m + 5])[0]
                    if uni == codepoint:
                        return gid
                    m += 5
            # Default UVS table: the codepoint uses its standard glyph.
            if default_off:
                t = o + default_off
                n_ranges = struct.unpack(">L", data[t:t + 4])[0]
                r = t + 4
                for _ in range(n_ranges):
                    start = (data[r] << 16) | (data[r + 1] << 8) | data[r + 2]
                    add_count = data[r + 3]
                    if start <= codepoint <= start + add_count:
                        return self._cmap12_lookup(codepoint)
                    r += 4
            return None
        return None

    # --- CBLC / CBDT bitmap extraction ------------------------------------

    def _ensure_strikes(self) -> list[_Strike]:
        if self._strikes is not None:
            return self._strikes
        data = self._data
        cblc_off, _ = self._table("CBLC")
        self._table("CBDT")  # presence check; offset read in extraction
        if cblc_off + 8 > len(data):
            raise EmojiFontError("truncated CBLC header")
        num_sizes = struct.unpack(">L", data[cblc_off + 4:cblc_off + 8])[0]
        strikes: list[_Strike] = []
        for i in range(num_sizes):
            base = cblc_off + 8 + i * 48
            if base + 48 > len(data):
                raise EmojiFontError("truncated CBLC bitmapSizeTable")
            ista_off, _ist_size, n_ist = struct.unpack(">LLL", data[base:base + 12])
            start_g, end_g = struct.unpack(">HH", data[base + 40:base + 44])
            ppem_x = data[base + 44]
            strikes.append(_Strike(
                index_array_off=cblc_off + ista_off,
                n_index_subtables=n_ist,
                start_glyph=start_g,
                end_glyph=end_g,
                ppem=ppem_x or 1,
            ))
        if not strikes:
            raise EmojiFontError("CBLC has no strikes")
        self._strikes = strikes
        return strikes

    def glyph_bitmap(self, gid: int) -> GlyphBitmap | None:
        """Extract glyph ``gid``'s color bitmap, or None if not present.

        Uses the first (largest) strike. Returns None for .notdef (gid 0)
        and any glyph absent from the strike's index subtables.
        """
        if gid in self._bitmap_cache:
            return self._bitmap_cache[gid]
        result = self._extract_bitmap(gid)
        self._bitmap_cache[gid] = result
        return result

    def _extract_bitmap(self, gid: int) -> GlyphBitmap | None:
        if gid == 0:
            return None
        data = self._data
        cbdt_off, _ = self._table("CBDT")
        strike = self._ensure_strikes()[0]
        arr = strike.index_array_off
        for k in range(strike.n_index_subtables):
            rec = arr + k * 8
            if rec + 8 > len(data):
                return None
            first_g, last_g, add_off = struct.unpack(">HHL", data[rec:rec + 8])
            if not (first_g <= gid <= last_g):
                continue
            ist = strike.index_array_off + add_off
            idx_fmt, _img_fmt, img_data_off = struct.unpack(">HHL", data[ist:ist + 8])
            if idx_fmt == 1:
                # variable-length: per-glyph offsets after the header
                rel = ist + 8 + (gid - first_g) * 4
                o1, o2 = struct.unpack(">LL", data[rel:rel + 8])
                glyph_off = cbdt_off + img_data_off + o1
                glyph_len = o2 - o1
            elif idx_fmt == 2:
                # constant-size glyphs
                img_size = struct.unpack(">L", data[ist + 8:ist + 12])[0]
                glyph_off = cbdt_off + img_data_off + (gid - first_g) * img_size
                glyph_len = img_size
            else:
                # formats 3/4/5 are rare in emoji fonts; treat as absent.
                return None
            if glyph_len <= 0:
                return None
            return self._decode_glyph_blob(
                data[glyph_off:glyph_off + glyph_len], strike.ppem
            )
        return None

    def _decode_glyph_blob(self, blob: bytes, ppem: int) -> GlyphBitmap | None:
        """Decode a CBDT glyph record (image format 17 or 18 = PNG)."""
        # We dispatch on the metrics shape rather than the index subtable's
        # imageFormat field (which we didn't thread through); both PNG
        # formats begin with their glyph metrics then a 4-byte length then
        # the PNG. Small metrics = 5 bytes, big metrics = 8 bytes. We detect
        # which by checking the PNG signature position.
        for metrics_len, unpacker in ((5, _small_metrics), (8, _big_metrics)):
            if len(blob) < metrics_len + 4:
                continue
            png_len = struct.unpack(">L", blob[metrics_len:metrics_len + 4])[0]
            png = blob[metrics_len + 4:metrics_len + 4 + png_len]
            if png[:8] == b"\x89PNG\r\n\x1a\n":
                h, w, bx, by, adv = unpacker(blob)
                return GlyphBitmap(
                    png=png, width=w, height=h,
                    bearing_x=bx, bearing_y=by, advance=adv, ppem=ppem,
                )
        return None

    # --- GSUB ligatures (emoji sequences) ---------------------------------

    @property
    def max_ligature_length(self) -> int:
        """Longest component-gid sequence in the ligature map (0 if none)."""
        self._ensure_ligatures()
        return self._max_ligature_len

    def lookup_ligature(self, component_gids: tuple[int, ...]) -> int | None:
        """Return the ligature glyph id for an exact component-gid sequence,
        or None if the font has no such ligature. The caller is responsible
        for trying progressively shorter prefixes (longest-match)."""
        self._ensure_ligatures()
        assert self._ligatures is not None
        return self._ligatures.get(component_gids)

    def _ensure_ligatures(self) -> None:
        if self._ligatures is not None:
            return
        ligatures: dict[tuple[int, ...], int] = {}
        # GSUB is optional; a font without it simply has no sequences.
        if "GSUB" not in self.tables:
            self._ligatures = ligatures
            return
        try:
            self._parse_gsub_ligatures(ligatures)
        except (struct.error, IndexError):
            # A malformed GSUB shouldn't kill emoji rendering — single
            # glyphs still work; we just lose sequence composition.
            ligatures = {}
        self._ligatures = ligatures
        self._max_ligature_len = max((len(k) for k in ligatures), default=0)

    def _parse_gsub_ligatures(self, out: dict[tuple[int, ...], int]) -> None:
        """Walk GSUB's lookup list and collect every type-4 (ligature)
        substitution as a component-gid-tuple -> ligature-gid mapping.

        We ignore script/feature selection and harvest *all* ligature
        lookups: for emoji fonts these are exactly the ZWJ/flag/keycap/
        skin-tone sequences, and applying them unconditionally is what a
        shaper would do for these scripts anyway.
        """
        data = self._data
        gsub_off, _ = self._table("GSUB")
        # Header 1.0: major(2) minor(2) scriptList(2) featureList(2)
        # lookupList(2). (1.1 adds a featureVariations offset we don't need.)
        lookup_list_off = gsub_off + struct.unpack(
            ">H", data[gsub_off + 8:gsub_off + 10]
        )[0]
        n_lookups = struct.unpack(">H", data[lookup_list_off:lookup_list_off + 2])[0]
        for i in range(n_lookups):
            lk_off = lookup_list_off + struct.unpack(
                ">H", data[lookup_list_off + 2 + i * 2:lookup_list_off + 4 + i * 2]
            )[0]
            lk_type, _flag, sub_count = struct.unpack(">HHH", data[lk_off:lk_off + 6])
            if lk_type != 4:
                continue
            for s in range(sub_count):
                sub_off = lk_off + struct.unpack(
                    ">H", data[lk_off + 6 + s * 2:lk_off + 8 + s * 2]
                )[0]
                self._parse_ligature_subtable(sub_off, out)

    def _parse_ligature_subtable(
        self, sub_off: int, out: dict[tuple[int, ...], int]
    ) -> None:
        data = self._data
        # LigatureSubst format 1: substFormat(2) coverage(2) ligSetCount(2)
        # then ligSetOffsets[]. Coverage gives the FIRST component glyph of
        # each ligature set, in order.
        _fmt, cov_rel, ligset_count = struct.unpack(">HHH", data[sub_off:sub_off + 6])
        first_gids = self._parse_coverage(sub_off + cov_rel)
        for li in range(ligset_count):
            if li >= len(first_gids):
                break
            ls_off = sub_off + struct.unpack(
                ">H", data[sub_off + 6 + li * 2:sub_off + 8 + li * 2]
            )[0]
            n_lig = struct.unpack(">H", data[ls_off:ls_off + 2])[0]
            first = first_gids[li]
            for g in range(n_lig):
                lig_off = ls_off + struct.unpack(
                    ">H", data[ls_off + 2 + g * 2:ls_off + 4 + g * 2]
                )[0]
                lig_gid, comp_count = struct.unpack(">HH", data[lig_off:lig_off + 4])
                # Components after the first are listed (comp_count - 1 gids).
                rest = tuple(
                    struct.unpack(">H", data[lig_off + 4 + c * 2:lig_off + 6 + c * 2])[0]
                    for c in range(comp_count - 1)
                )
                out[(first,) + rest] = lig_gid

    def _parse_coverage(self, cov_off: int) -> list[int]:
        """Parse a Coverage table (format 1 or 2) into an ordered gid list."""
        data = self._data
        fmt = struct.unpack(">H", data[cov_off:cov_off + 2])[0]
        gids: list[int] = []
        if fmt == 1:
            count = struct.unpack(">H", data[cov_off + 2:cov_off + 4])[0]
            for k in range(count):
                gids.append(struct.unpack(">H", data[cov_off + 4 + k * 2:cov_off + 6 + k * 2])[0])
        elif fmt == 2:
            count = struct.unpack(">H", data[cov_off + 2:cov_off + 4])[0]
            for k in range(count):
                start, end, _idx = struct.unpack(
                    ">HHH", data[cov_off + 4 + k * 6:cov_off + 10 + k * 6]
                )
                gids.extend(range(start, end + 1))
        return gids


@dataclass(frozen=True)
class _Strike:
    """One CBLC strike (bitmap size): where its index subtables live and
    which glyph range + ppem it covers."""
    index_array_off: int
    n_index_subtables: int
    start_glyph: int
    end_glyph: int
    ppem: int


def _small_metrics(blob: bytes) -> tuple[int, int, int, int, int]:
    """SmallGlyphMetrics: height, width, bearingX, bearingY, advance."""
    h, w, bx, by, adv = struct.unpack(">BBbbB", blob[:5])
    return h, w, bx, by, adv


def _big_metrics(blob: bytes) -> tuple[int, int, int, int, int]:
    """BigGlyphMetrics: height, width, horiBearingX/Y, horiAdvance (+vert,
    ignored). Returns the horizontal metrics in the small-metrics shape."""
    h, w, hbx, hby, hadv = struct.unpack(">BBbbB", blob[:5])
    return h, w, hbx, hby, hadv
