"""Codepoint/glyph-id-keyed text measurement over an embedded TrueType font.

This is the measurement layer of inkmd's font-embedding path (Spine 2). It is
a **sibling** to the WinAnsi base-14 path in :mod:`inkmd.fonts`, not a
replacement: the base-14 path keeps measuring Helvetica/Times/Courier from its
AFM width tables keyed on a WinAnsi byte. This module instead reads advances
straight from an embedded :class:`~inkmd.truetype.TrueTypeFont` (via S1's
``advance_width``), so it can measure any codepoint the font's ``cmap`` covers,
including CJK/Cyrillic/Greek/extended-Latin that the WinAnsi byte path collapses
to ``?``.

It emits no PDF (that is S3) and does not rewire the existing ``text_width``
callers in layout/render (that is S3/S5 wiring, once font selection exists).
S2 is the measurement primitive and its tests, in isolation.

Two deliberate, honest limitations of this path in v0.4:

* **Scaling is by the font's own ``units_per_em``**, never a hardcoded 1000.
  A base-14 em is 1000 design units; a TrueType em is commonly 1000 or 2048.
  Width in points is ``advance * size / units_per_em`` with ``advance`` and
  ``units_per_em`` read from the font. :func:`embedded_text_width` sums advances
  in design units then scales once, mirroring the WinAnsi path's
  ``total / 1000.0 * size`` arithmetic (integer accumulation, single scale).
* **Text is measured UNKERNED.** The WinAnsi path kerns via AFM pair tables
  keyed by glyph name (``fonts.kerning_adjustment``); embedded-TrueType kerning
  lives in ``kern``/``GPOS`` tables that S1 does not parse and that are out of
  scope for v0.4 (GPOS positioning is shaping-adjacent, a 1.0 concern). So
  :func:`embedded_text_width` applies no pair adjustment between glyphs.
"""

from __future__ import annotations

from inkmd.fonts import is_zero_width_codepoint
from inkmd.truetype import TrueTypeFont


def embedded_char_width(font: TrueTypeFont, codepoint: int, size: float) -> float:
    """Return the rendered width of one ``codepoint`` in ``font``, in points.

    The codepoint is mapped to a glyph id via :meth:`TrueTypeFont.glyph_id`; its
    advance is read in design units via :meth:`TrueTypeFont.advance_width` and
    scaled to points as ``advance * size / font.units_per_em``. The scale base
    is the font's own ``units_per_em`` (read from the font, never hardcoded),
    so a 2048-unit em scales correctly.

    Zero-width formatting characters (soft hyphen, etc.) measure 0, using the
    same :func:`inkmd.fonts.is_zero_width_codepoint` set as the WinAnsi path so
    the two paths agree on what is non-printing. A real combining mark to which
    the font itself assigns a zero advance already measures 0 via
    ``advance_width``; it is not double-handled.

    A codepoint ABSENT from the font's ``cmap`` maps to glyph id 0 (.notdef) and
    is measured at gid 0's **real** advance (the font's .notdef box width), NOT
    a convenient 0. A missing glyph reserves real layout space (S6 later turns
    it into a visible marker); pretending it is zero-width would silently
    corrupt layout the moment a non-Latin run renders.
    """
    if is_zero_width_codepoint(codepoint):
        return 0.0
    gid = font.glyph_id(codepoint)
    advance = font.advance_width(gid)
    return advance * size / font.units_per_em


def embedded_text_width(font: TrueTypeFont, text: str, size: float) -> float:
    """Return the rendered width of ``text`` in ``font``, in points.

    This is the **unkerned** measurement of ``text``, with the same zero-width-
    formatting-character drop as the WinAnsi ``text_width`` (a soft hyphen and
    similar contribute nothing).

    Unkerned is deliberate in v0.4: embedded-TrueType kerning lives in
    ``kern``/``GPOS`` tables that are out of scope (see the module docstring),
    so no pair adjustment is applied.

    Arithmetic structure matches the WinAnsi ``text_width`` exactly: advances
    are summed in DESIGN units (integers, left-to-right) and scaled to points
    ONCE at the end (``total / units_per_em * size``), where the WinAnsi path
    does ``total / 1000.0 * size``. Integer accumulation then a single scale is
    exact and order-independent, so cross-Python determinism holds; do not
    reorder it or fold the scale into the loop.
    """
    total = 0
    for ch in text:
        cp = ord(ch)
        if is_zero_width_codepoint(cp):
            continue
        total += font.advance_width(font.glyph_id(cp))
    return total / font.units_per_em * size


def embedded_advance(font: TrueTypeFont, codepoint: int) -> int:
    """Return ``codepoint``'s advance in the font's DESIGN units (unscaled).

    A thin pass-through over :meth:`TrueTypeFont.glyph_id` +
    :meth:`TrueTypeFont.advance_width`, returning the integer design-unit
    advance S3's ``/W`` array needs (paired with ``font.units_per_em``). It does
    NOT apply the zero-width-codepoint drop: that is a measurement concern, and
    a ``/W`` entry must reflect the glyph's true advance. Use
    :func:`embedded_char_width` for measurement; use this only to feed emission.
    """
    return font.advance_width(font.glyph_id(codepoint))
