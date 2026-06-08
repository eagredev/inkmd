"""Line spacing (leading) through LayoutConfig (v0.5 S3).

S0 added ``LayoutConfig.line_spacing`` and the fold layer but left it
unconnected. S3 threads ``effective.line_spacing`` from ``compile`` into the
two leading consumers:

  - prose: ``styled_pdf`` gained a keyword-only ``line_height_ratio`` passed
    to ``paginate_runs``, where per-line height is ``ratio * max font size on
    the line`` (layout.py). The default keyword (1.2) mirrors the historical
    ``paginate_runs`` default, so a default compile is byte-identical.
  - tables: ``render_document`` (and ``_render_block`` / ``_render_list`` /
    ``_render_blockquote``) gained a keyword-only ``line_spacing`` threaded to
    ``_render_table``, where row line height is ``body_size * line_spacing``.
    The default keyword is ``TABLE_LINE_HEIGHT_RATIO`` (1.2), so a default
    table is byte-identical. Tables follow the knob the same way they follow
    font_size, so a table breathes with the rest of the document.

These tests pin that the wiring took effect for prose AND tables by the same
multiplier:

  - a non-default line_spacing changes the output bytes (default untouched,
    which the frozen baseline proves separately),
  - the flat keyword and a ``LayoutConfig`` agree, and the flat keyword still
    wins over the config,
  - prose: the baseline-to-baseline distance scales with line_spacing; at
    spacing=2.4 (2x the default) the per-line advance is exactly double the
    spacing=1.2 advance, asserted on extracted ``Tm`` baseline y-origins,
  - tables: a table's row pitch grows with line_spacing (asserted on the
    extracted row baseline y-origins) and differs from the default,
  - font_size and line_spacing both flow into table line height and compose,
  - line_spacing=0 degrades (overlapping lines) without crashing.
"""

from __future__ import annotations

import re
import zlib

import inkmd
from inkmd import LayoutConfig


# A single paragraph with enough words to wrap onto several lines, so the
# line-to-line leading is measurable from consecutive baseline y-origins.
PROSE_DOC = (
    "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu "
    "xi omicron pi rho sigma tau upsilon phi chi psi omega and more words to "
    "force several wrapped lines in this single paragraph block so we can "
    "measure the baseline to baseline distance directly from the stream.\n"
)

# A multi-row table for the row-pitch checks. Tables have no headings, so
# every text line is a cell row at body size.
TABLE_DOC = (
    "| Name | Value | Note |\n"
    "| --- | --- | --- |\n"
    "| alpha | one | first row of the table |\n"
    "| beta | two | second row of the table |\n"
    "| gamma | three | third row of the table |\n"
)


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


def _distinct_baseline_ys(pdf_bytes: bytes) -> list[float]:
    """Distinct text-line baseline y-origins, top of page first.

    styled_pdf emits each run's text matrix as ``1 0 0 1 x y Tm``. Several
    runs on one wrapped line share a y, so the DISTINCT y values are the
    per-line baselines; consecutive differences are the leading.
    """
    ys: set[float] = set()
    for stream in _decoded_streams(pdf_bytes):
        for m in re.finditer(rb"1 0 0 1 -?[\d.]+ (-?[\d.]+) Tm", stream):
            ys.add(round(float(m.group(1)), 4))
    return sorted(ys, reverse=True)


def _consecutive_diffs(ys: list[float]) -> list[float]:
    return [round(ys[i] - ys[i + 1], 4) for i in range(len(ys) - 1)]


# --- A non-default line_spacing changes output ----------------------------


def test_nondefault_line_spacing_changes_bytes():
    assert inkmd.compile(PROSE_DOC, line_spacing=1.5) != inkmd.compile(PROSE_DOC)


def test_default_and_explicit_1_2_are_byte_identical():
    # compile(md) and compile(md, line_spacing=1.2) must be the same bytes;
    # 1.2 is the historical default on both the prose and table paths.
    assert inkmd.compile(PROSE_DOC, line_spacing=1.2) == inkmd.compile(PROSE_DOC)


def test_flat_line_spacing_matches_config_line_spacing():
    flat = inkmd.compile(PROSE_DOC, line_spacing=1.5)
    via_config = inkmd.compile(PROSE_DOC, layout=LayoutConfig(line_spacing=1.5))
    assert flat == via_config


def test_flat_line_spacing_wins_over_config_line_spacing():
    # layout sets 1.5, flat keyword sets 2.0: flat wins, so the result must
    # equal compiling with line_spacing=2.0 alone.
    mixed = inkmd.compile(
        PROSE_DOC, layout=LayoutConfig(line_spacing=1.5), line_spacing=2.0
    )
    assert mixed == inkmd.compile(PROSE_DOC, line_spacing=2.0)


# --- Prose leading semantic check (baseline-to-baseline distance) ---------


def test_prose_default_baseline_distance_is_one_point_two_times_body():
    # At the default body size (12) and spacing 1.2 the per-line advance is
    # 1.2 * 12 = 14.4, the historical leading.
    ys = _distinct_baseline_ys(inkmd.compile(PROSE_DOC, line_spacing=1.2))
    diffs = _consecutive_diffs(ys)
    assert len(diffs) >= 2  # the paragraph wrapped to several lines
    assert all(d == 14.4 for d in diffs)


def test_prose_baseline_distance_doubles_at_2x():
    # spacing=2.4 is exactly 2x the default 1.2, so the per-line advance is
    # exactly double: 28.8 vs 14.4. Method: extract the distinct Tm baseline
    # y-origins and diff consecutive ones.
    diffs_1_2 = _consecutive_diffs(
        _distinct_baseline_ys(inkmd.compile(PROSE_DOC, line_spacing=1.2))
    )
    diffs_2_4 = _consecutive_diffs(
        _distinct_baseline_ys(inkmd.compile(PROSE_DOC, line_spacing=2.4))
    )
    assert all(d == 14.4 for d in diffs_1_2)
    assert all(d == 28.8 for d in diffs_2_4)
    # The 2x relationship holds line for line.
    assert diffs_2_4[0] == diffs_1_2[0] * 2


def test_prose_tight_baseline_distance():
    # spacing=1.0 gives a per-line advance of exactly the body size (12.0),
    # tighter than the 14.4 default.
    diffs = _consecutive_diffs(
        _distinct_baseline_ys(inkmd.compile(PROSE_DOC, line_spacing=1.0))
    )
    assert all(d == 12.0 for d in diffs)


# --- Table row leading semantic check (row pitch) -------------------------


def test_table_row_pitch_grows_with_line_spacing():
    # A table's row pitch is the distance between consecutive row baselines.
    # It must grow when line_spacing grows, proving tables follow the knob.
    pitch_default = _consecutive_diffs(
        _distinct_baseline_ys(inkmd.compile(TABLE_DOC, line_spacing=1.2))
    )
    pitch_loose = _consecutive_diffs(
        _distinct_baseline_ys(inkmd.compile(TABLE_DOC, line_spacing=1.8))
    )
    assert len(pitch_default) >= 2  # the table has several rows
    # Single-line rows: pitch = body_size * line_spacing + 2 * cell padding.
    # At body 12 the padded pitch is 20.4 (default) and 27.6 (loose); every
    # consecutive gap matches, and the loose gaps are strictly larger.
    assert all(p == 20.4 for p in pitch_default)
    assert all(p == 27.6 for p in pitch_loose)
    assert pitch_loose[0] > pitch_default[0]


def test_table_bytes_change_with_line_spacing():
    assert inkmd.compile(TABLE_DOC, line_spacing=1.8) != inkmd.compile(TABLE_DOC)


def test_table_default_byte_identical():
    assert inkmd.compile(TABLE_DOC, line_spacing=1.2) == inkmd.compile(TABLE_DOC)


# --- font_size and line_spacing compose into table line height ------------


def test_font_size_and_line_spacing_compose():
    # Both knobs flow into table row line height (body_size * line_spacing).
    # The combined change must differ from each single-knob change and from
    # the default.
    both = inkmd.compile(TABLE_DOC, font_size=16, line_spacing=1.5)
    only_font = inkmd.compile(TABLE_DOC, font_size=16)
    only_spacing = inkmd.compile(TABLE_DOC, line_spacing=1.5)
    default = inkmd.compile(TABLE_DOC)
    assert both != only_font
    assert both != only_spacing
    assert both != default


def test_table_pitch_with_both_knobs():
    # At font_size=24 and line_spacing=1.5 the un-padded row line height is
    # 24 * 1.5 = 36; with 2 * cell padding (6) the pitch is 42.0.
    pitch = _consecutive_diffs(
        _distinct_baseline_ys(
            inkmd.compile(TABLE_DOC, font_size=24, line_spacing=1.5)
        )
    )
    assert all(p == 42.0 for p in pitch)


# --- Defaults and degenerate inputs ---------------------------------------


def test_line_spacing_zero_returns_bytes_without_crashing():
    # A zero multiplier collapses leading to nothing (lines overlap). S3 adds
    # no clamping; it must still produce a valid PDF rather than crash or
    # hang. Mixed doc so both the prose and table paths see the value.
    doc = (
        TABLE_DOC
        + "\nA body paragraph with enough words to wrap onto two lines here "
        "for the degenerate-spacing check.\n"
    )
    out = inkmd.compile(doc, line_spacing=0)
    assert isinstance(out, bytes)
    assert out[:4] == b"%PDF"


def test_tiny_line_spacing_returns_bytes():
    out = inkmd.compile(PROSE_DOC, line_spacing=0.01)
    assert isinstance(out, bytes)
    assert out[:4] == b"%PDF"


def test_empty_doc_does_not_crash_with_line_spacing():
    out = inkmd.compile("", line_spacing=1.5)
    assert isinstance(out, bytes)
    assert out[:4] == b"%PDF"
