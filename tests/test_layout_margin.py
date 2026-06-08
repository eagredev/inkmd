"""Margin wiring through LayoutConfig to the render path (v0.5 S1).

S0 added ``LayoutConfig.margin`` and the fold layer but left margin
unconnected to the renderer. S1 threads ``effective.margin`` from
``compile`` through ``styled_pdf`` into ``paginate_runs`` and into the
content-width calculation, so a non-default margin actually changes the
page geometry. These tests pin that the wiring took effect:

  - a non-default margin changes the output bytes (default is untouched,
    which the frozen baseline proves separately),
  - the flat keyword and a ``LayoutConfig`` agree, and the flat keyword
    still wins over the config,
  - the margin moves BOTH the text x-origin (further right at a larger
    margin) AND the content column width (a long paragraph wraps to more
    lines at a larger margin), and
  - a degenerate over-wide margin degrades without crashing.
"""

from __future__ import annotations

import re
import zlib

import inkmd
from inkmd import LayoutConfig
from inkmd.layout import Run, paginate_runs


# A paragraph long enough to wrap several times at body size, so a change
# in column width changes the line count.
LONG_PARA = (
    "The quick brown fox jumps over the lazy dog while the industrious "
    "bee gathers nectar from a hundred blossoms in the warm afternoon "
    "sun beside the slow river. "
) * 4

DOC = "# Heading\n\n" + LONG_PARA.strip()


def _decoded_streams(pdf_bytes: bytes) -> list[bytes]:
    """Return every content stream, FlateDecoded where it decompresses."""
    out: list[bytes] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.DOTALL):
        raw = m.group(1)
        try:
            out.append(zlib.decompress(raw))
        except zlib.error:
            out.append(raw)
    return out


def _first_text_x(pdf_bytes: bytes) -> float | None:
    """First text x-origin: the x of the first ``Tm`` that precedes a
    text-show operator in any content stream. Mirrors how styled_pdf
    emits each run as ``1 0 0 1 x y Tm`` followed by Tj/TJ."""
    for stream in _decoded_streams(pdf_bytes):
        for tm in re.finditer(rb"1 0 0 1 (-?[\d.]+) (-?[\d.]+) Tm", stream):
            tail = stream[tm.end():tm.end() + 200]
            if b" Tj" in tail or b" TJ" in tail:
                return float(tm.group(1))
    return None


# --- A non-default margin changes output ----------------------------------


def test_nondefault_margin_changes_bytes():
    assert inkmd.compile(DOC, margin=54) != inkmd.compile(DOC)


def test_flat_margin_matches_config_margin():
    flat = inkmd.compile(DOC, margin=54)
    via_config = inkmd.compile(DOC, layout=LayoutConfig(margin=54))
    assert flat == via_config


def test_flat_margin_wins_over_config_margin():
    # layout sets 54, flat keyword sets 36: flat wins, so the result must
    # equal compiling with margin=36 alone.
    mixed = inkmd.compile(DOC, layout=LayoutConfig(margin=54), margin=36)
    assert mixed == inkmd.compile(DOC, margin=36)


# --- The margin moves the text, not just the bytes ------------------------


def test_margin_moves_text_origin_right():
    # A larger margin pushes the first text x-origin to the right by the
    # margin delta. 72 -> 144 should move it right by ~72pt.
    x72 = _first_text_x(inkmd.compile(DOC, margin=72))
    x144 = _first_text_x(inkmd.compile(DOC, margin=144))
    assert x72 is not None and x144 is not None
    assert x72 == 72.0
    assert x144 == 144.0
    assert x144 - x72 == 72.0


def test_larger_margin_narrows_column_and_wraps_sooner():
    # Drive the pagination layer directly: a larger margin narrows the
    # content column, so the same paragraph wraps to more lines. This,
    # together with the x-origin test, proves the margin feeds BOTH the
    # x-origin and the column width (not just one).
    block = [Run(LONG_PARA.strip(), "Helvetica", 12)]

    def line_count(margin: float) -> int:
        pages = paginate_runs(
            [block], page_width=612, page_height=792, margin=margin
        )
        return sum(len(p.lines) for p in pages)

    narrow_margin_lines = line_count(72)
    wide_margin_lines = line_count(180)
    assert wide_margin_lines > narrow_margin_lines


def test_first_run_x_tracks_margin_in_pagination():
    block = [Run("hello world", "Helvetica", 12)]
    for margin in (36, 72, 144):
        pages = paginate_runs(
            [block], page_width=612, page_height=792, margin=margin
        )
        first_x = pages[0].lines[0].runs[0].x
        assert first_x == margin


# --- Degenerate margin degrades without crashing --------------------------


def test_overwide_margin_returns_bytes_without_crashing():
    # margin=400 on a 612pt-wide letter page leaves a negative column.
    # S1 adds no clamping; the contract is only that it must not raise or
    # hang. It must still return bytes.
    out = inkmd.compile(DOC, margin=400)
    assert isinstance(out, bytes)
    assert out[:4] == b"%PDF"
