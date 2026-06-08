"""Body font size + proportional heading scale through LayoutConfig (v0.5 S2).

S0 added ``LayoutConfig.font_size`` and the fold layer but left it
unconnected. S2 threads ``effective.font_size`` from ``compile`` into
``render_document`` (a keyword-only ``body_size`` param) and through every
helper that builds runs, so body text, list markers, table cells, and
captions render at that size. Headings scale off it: ``_heading_size(level,
body)`` returns ``body / BODY_SIZE * HEADING_SIZES[level]``, which at
``body == 12`` reproduces the original ``{24,18,14,13,12,11}`` exactly and at
``body == 24`` doubles every level. These tests pin that the wiring took
effect for body AND headings AND table cells by the same factor:

  - a non-default font_size changes the output bytes (default untouched,
    which the frozen baseline proves separately),
  - the flat keyword and a ``LayoutConfig`` agree, and the flat keyword
    still wins over the config,
  - at font_size=12 the resolved heading sizes are exactly the originals;
    at font_size=24 (2x) each heading doubles and body runs are 24, both
    asserted on the ratio helper AND on extracted ``Tf`` sizes,
  - a table's cell text and line height scale with font_size, and
  - a no-heading doc and an empty doc render at the effective size without
    crashing.
"""

from __future__ import annotations

import re
import zlib

import inkmd
from inkmd import LayoutConfig
from inkmd.render import BODY_SIZE, HEADING_SIZES, _heading_size


# One document carrying all six heading levels plus a body paragraph, used
# for the semantic Tf-extraction checks.
ALL_HEADINGS = (
    "# H1\n\n## H2\n\n### H3\n\n#### H4\n\n##### H5\n\n###### H6\n\n"
    "Body paragraph with enough words to wrap and show body run sizing.\n"
)

# A small table for the "did everything follow body" guard.
TABLE_DOC = (
    "| Name | Value | Note |\n"
    "| --- | --- | --- |\n"
    "| alpha | one | first row of the table |\n"
    "| beta | two | second row of the table |\n"
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


def _tf_sizes(pdf_bytes: bytes) -> list[float]:
    """Every ``/Fn <size> Tf`` size found in the content streams.

    styled_pdf emits each run's font selection as ``/Fn size Tf``, so the
    set of sizes present is the set of point sizes the document actually
    renders at.
    """
    sizes: list[float] = []
    for stream in _decoded_streams(pdf_bytes):
        for m in re.finditer(rb"/F\d+\s+([\d.]+)\s+Tf", stream):
            sizes.append(float(m.group(1)))
    return sizes


# --- The ratio helper reproduces the originals exactly --------------------


def test_heading_size_helper_exact_at_default():
    # At the default body size the scale factor is exactly 1.0, so every
    # level must equal its original float bit for bit (this is what keeps
    # the byte baseline green).
    resolved = {level: _heading_size(level, BODY_SIZE) for level in range(1, 7)}
    assert resolved == {1: 24.0, 2: 18.0, 3: 14.0, 4: 13.0, 5: 12.0, 6: 11.0}
    assert resolved == dict(HEADING_SIZES)


def test_heading_size_helper_doubles_at_2x():
    # body=24 is exactly 2x the default, so each heading is exactly double.
    resolved = {level: _heading_size(level, 24.0) for level in range(1, 7)}
    assert resolved == {1: 48.0, 2: 36.0, 3: 28.0, 4: 26.0, 5: 24.0, 6: 22.0}


# --- A non-default font_size changes output -------------------------------


def test_nondefault_font_size_changes_bytes():
    assert inkmd.compile(ALL_HEADINGS, font_size=16) != inkmd.compile(ALL_HEADINGS)


def test_default_and_explicit_12_are_byte_identical():
    # compile(md) and compile(md, font_size=12) must be the same bytes; the
    # ratio math is exact at the default.
    assert inkmd.compile(ALL_HEADINGS, font_size=12) == inkmd.compile(ALL_HEADINGS)


def test_flat_font_size_matches_config_font_size():
    flat = inkmd.compile(ALL_HEADINGS, font_size=16)
    via_config = inkmd.compile(ALL_HEADINGS, layout=LayoutConfig(font_size=16))
    assert flat == via_config


def test_flat_font_size_wins_over_config_font_size():
    # layout sets 16, flat keyword sets 20: flat wins, so the result must
    # equal compiling with font_size=20 alone.
    mixed = inkmd.compile(
        ALL_HEADINGS, layout=LayoutConfig(font_size=16), font_size=20
    )
    assert mixed == inkmd.compile(ALL_HEADINGS, font_size=20)


# --- Heading-scale semantic check (body AND headings move together) -------


def test_heading_and_body_tf_sizes_at_default():
    # The document has six heading levels plus body text. Extracting the Tf
    # sizes from the content stream must surface exactly the six heading
    # sizes (H5 == 12 coincides with body 12, so the distinct set is six
    # values) and nothing larger or smaller.
    sizes = set(_tf_sizes(inkmd.compile(ALL_HEADINGS, font_size=12)))
    assert sizes == {11.0, 12.0, 13.0, 14.0, 18.0, 24.0}


def test_heading_and_body_tf_sizes_double_at_2x():
    # At font_size=24 every Tf size is exactly double the default. body=24
    # coincides with H5=24, so the distinct set is the six doubled heading
    # sizes; the presence of 24 proves both body and H5 render at 24.
    sizes = set(_tf_sizes(inkmd.compile(ALL_HEADINGS, font_size=24)))
    assert sizes == {22.0, 24.0, 26.0, 28.0, 36.0, 48.0}
    # Each default size's double is present.
    for original in (11.0, 12.0, 13.0, 14.0, 18.0, 24.0):
        assert original * 2 in sizes


def test_body_run_size_scales():
    # A heading-free paragraph: the only Tf size present is the body size,
    # so it must equal the requested font_size.
    body_only = "Just a paragraph of body text with several words.\n"
    assert set(_tf_sizes(inkmd.compile(body_only, font_size=12))) == {12.0}
    assert set(_tf_sizes(inkmd.compile(body_only, font_size=16))) == {16.0}
    assert set(_tf_sizes(inkmd.compile(body_only, font_size=9))) == {9.0}


# --- Table cells scale with body ------------------------------------------


def test_table_cell_text_scales_with_font_size():
    # The "did everything follow body" guard: a table at a non-default size
    # differs from the default, and its cell text Tf size equals the body
    # size (tables have no headings, so every Tf is a cell at body size).
    assert inkmd.compile(TABLE_DOC, font_size=18) != inkmd.compile(TABLE_DOC)
    assert set(_tf_sizes(inkmd.compile(TABLE_DOC, font_size=12))) == {12.0}
    assert set(_tf_sizes(inkmd.compile(TABLE_DOC, font_size=18))) == {18.0}


def test_table_line_height_scales_with_font_size():
    # Cell text bigger -> taller rows -> the table occupies more vertical
    # space, so a larger-font table is more bytes / different geometry than
    # the default. Compare the rendered y-coordinates: the larger font must
    # push content lower (smaller y in PDF bottom-up space) or add pages.
    small = inkmd.compile(TABLE_DOC, font_size=9)
    large = inkmd.compile(TABLE_DOC, font_size=20)
    assert small != large
    # Lowest text-baseline y in each: bigger line height means the last row
    # sits lower on the page (a smaller y value).
    def min_text_y(pdf: bytes) -> float:
        ys: list[float] = []
        for stream in _decoded_streams(pdf):
            for m in re.finditer(rb"1 0 0 1 -?[\d.]+ (-?[\d.]+) Tm", stream):
                ys.append(float(m.group(1)))
        return min(ys) if ys else float("inf")
    assert min_text_y(large) < min_text_y(small)


# --- Fenced code blocks scale with body (0.875 ratio) ---------------------

# A fenced code block plus surrounding body text. Fenced code renders at
# 0.875x body (10.5 at the default), so the distinct Tf set is the body size
# plus the code size.
CODE_DOC = (
    "Body text before the block.\n\n"
    "```\n"
    "code line one\n"
    "code line two\n"
    "```\n\n"
    "Body text after the block.\n"
)


def test_fenced_code_size_at_default():
    # At the default body size the fenced-code Tf is exactly 10.5 and the
    # body Tf is 12.0; nothing else is present.
    assert set(_tf_sizes(inkmd.compile(CODE_DOC, font_size=12))) == {10.5, 12.0}


def test_fenced_code_size_scales_at_2x():
    # At font_size=24 both sizes double exactly: code 21.0, body 24.0.
    assert set(_tf_sizes(inkmd.compile(CODE_DOC, font_size=24))) == {21.0, 24.0}


def test_fenced_code_changes_bytes_off_default():
    assert inkmd.compile(CODE_DOC, font_size=16) != inkmd.compile(CODE_DOC)


# --- Defaults and degenerate inputs ---------------------------------------


def test_no_heading_doc_renders_at_effective_size():
    doc = "First paragraph here.\n\nSecond paragraph with more words to wrap.\n"
    assert set(_tf_sizes(inkmd.compile(doc, font_size=14))) == {14.0}


def test_empty_doc_does_not_crash():
    out = inkmd.compile("", font_size=16)
    assert isinstance(out, bytes)
    assert out[:4] == b"%PDF"


def test_blank_line_doc_does_not_crash():
    out = inkmd.compile("para one\n\n\n\npara two\n", font_size=16)
    assert isinstance(out, bytes)
    assert out[:4] == b"%PDF"


def test_list_markers_scale_with_font_size():
    # List markers are emitted at the body size; a non-default size changes
    # the output and a heading-free list shows only the body Tf size.
    doc = "- first item\n- second item\n- third item\n"
    assert inkmd.compile(doc, font_size=16) != inkmd.compile(doc)
    assert set(_tf_sizes(inkmd.compile(doc, font_size=16))) == {16.0}
