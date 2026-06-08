"""Page geometry: named sizes, custom dimensions, orientation (v0.5 S4).

S4 widens ``LayoutConfig.page_size`` to accept either a known size name
(case-insensitive) or a custom ``(width, height)`` tuple in points, adds an
``orientation`` field ("portrait"/"landscape"), and threads the resolved
dimensions to both the content-width calc and the PDF MediaBox. These tests
pin the resolution helper, the MediaBox the resolved size produces, the
case-insensitive name lookup, the landscape swap (for named AND custom
sizes), the wider content column landscape gives, the flat-override path,
and the error contract. Byte-identity at the defaults is proven by the
frozen validation baseline; here we prove the new surface behaves.
"""

from __future__ import annotations

import re

import pytest

import inkmd
from inkmd import LayoutConfig
from inkmd.pdf import PAGE_SIZES, resolve_page_size


SAMPLE = "# Title\n\nA paragraph of body text that wraps a little.\n\n- one\n- two\n"

# The conventional 72-dpi points for each named size, portrait (h >= w).
EXPECTED_POINTS = {
    "letter": (612, 792),
    "legal": (612, 1008),
    "tabloid": (792, 1224),
    "a3": (842, 1191),
    "a4": (595, 842),
    "a5": (420, 595),
}


def mediabox(pdf: bytes) -> tuple[str, str]:
    """Extract the first /MediaBox width and height as strings from PDF bytes."""
    m = re.search(rb"/MediaBox \[0 0 (\S+) (\S+)\]", pdf)
    assert m is not None, "no /MediaBox found in output"
    return m.group(1).decode("ascii"), m.group(2).decode("ascii")


def page_count(pdf: bytes) -> int:
    """Read the page tree /Count from PDF bytes."""
    m = re.search(rb"/Count (\d+)", pdf)
    assert m is not None, "no /Count found in output"
    return int(m.group(1))


# --- the resolution helper -------------------------------------------------


@pytest.mark.parametrize("name,points", sorted(EXPECTED_POINTS.items()))
def test_named_sizes_resolve_to_expected_points(name, points):
    assert resolve_page_size(name) == points


def test_table_keyed_lowercase_with_all_expected_names():
    assert dict(sorted(PAGE_SIZES.items())) == dict(sorted(EXPECTED_POINTS.items()))


def test_resolve_case_insensitive_names():
    assert (
        resolve_page_size("letter")
        == resolve_page_size("Letter")
        == resolve_page_size("LETTER")
        == (612, 792)
    )
    assert resolve_page_size("A4") == resolve_page_size("a4") == (595, 842)


def test_resolve_custom_tuple():
    assert resolve_page_size((400, 600)) == (400.0, 600.0)


def test_resolve_custom_list_also_accepted():
    assert resolve_page_size([500, 500]) == (500.0, 500.0)


def test_resolve_landscape_swaps_named():
    assert resolve_page_size("letter", "landscape") == (792, 612)
    assert resolve_page_size("a4", "landscape") == (842, 595)


def test_resolve_landscape_case_insensitive():
    assert resolve_page_size("letter", "LANDSCAPE") == (792, 612)


def test_resolve_landscape_swaps_custom():
    assert resolve_page_size((400, 600), "landscape") == (600.0, 400.0)


def test_resolve_portrait_is_default_and_noop():
    assert resolve_page_size("a3") == resolve_page_size("a3", "portrait")


# --- the resolution error contract -----------------------------------------


def test_resolve_unknown_name_raises_keyerror():
    with pytest.raises(KeyError):
        resolve_page_size("foolscap")


def test_resolve_unknown_name_message_lists_valid():
    with pytest.raises(KeyError) as exc:
        resolve_page_size("foolscap")
    msg = str(exc.value)
    assert "foolscap" in msg
    assert "letter" in msg and "a4" in msg


@pytest.mark.parametrize("bad", [(400,), (400, 600, 700), ()])
def test_resolve_wrong_length_tuple_raises_valueerror(bad):
    with pytest.raises(ValueError):
        resolve_page_size(bad)


@pytest.mark.parametrize("bad", [(400, "x"), ("w", 600), (400, None)])
def test_resolve_non_numeric_dim_raises_valueerror(bad):
    with pytest.raises(ValueError):
        resolve_page_size(bad)


@pytest.mark.parametrize("bad", [(0, 600), (-5, 600), (400, 0), (400, -1)])
def test_resolve_non_positive_dim_raises_valueerror(bad):
    with pytest.raises(ValueError):
        resolve_page_size(bad)


def test_resolve_bool_dim_rejected():
    with pytest.raises(ValueError):
        resolve_page_size((True, 600))


def test_resolve_invalid_orientation_raises_valueerror():
    with pytest.raises(ValueError):
        resolve_page_size("letter", "sideways")


# --- compile(): named sizes reach the MediaBox -----------------------------


@pytest.mark.parametrize("name,points", sorted(EXPECTED_POINTS.items()))
def test_compile_named_size_mediabox(name, points):
    pdf = inkmd.compile(SAMPLE, page_size=name)
    w, h = points
    assert mediabox(pdf) == (str(w), str(h))


def test_compile_legal_mediabox():
    assert mediabox(inkmd.compile(SAMPLE, page_size="legal")) == ("612", "1008")


def test_compile_a3_mediabox():
    assert mediabox(inkmd.compile(SAMPLE, page_size="a3")) == ("842", "1191")


def test_compile_a5_mediabox():
    assert mediabox(inkmd.compile(SAMPLE, page_size="a5")) == ("420", "595")


# --- compile(): case-insensitivity is byte-identical -----------------------


def test_compile_letter_case_insensitive_byte_identical():
    a = inkmd.compile(SAMPLE, page_size="letter")
    assert a == inkmd.compile(SAMPLE, page_size="Letter")
    assert a == inkmd.compile(SAMPLE, page_size="LETTER")


def test_compile_a4_case_insensitive_byte_identical():
    assert inkmd.compile(SAMPLE, page_size="A4") == inkmd.compile(SAMPLE, page_size="a4")


def test_compile_default_equals_explicit_letter_byte_identical():
    assert inkmd.compile(SAMPLE) == inkmd.compile(SAMPLE, page_size="letter")


# --- compile(): custom tuple -----------------------------------------------


def test_compile_custom_tuple_mediabox():
    pdf = inkmd.compile(SAMPLE, layout=LayoutConfig(page_size=(400, 600)))
    # Custom dimensions are emitted as floats in the MediaBox.
    assert mediabox(pdf) == ("400.0", "600.0")


def test_compile_custom_square_mediabox():
    pdf = inkmd.compile(SAMPLE, layout=LayoutConfig(page_size=(500, 500)))
    assert mediabox(pdf) == ("500.0", "500.0")


# --- compile(): orientation ------------------------------------------------


def test_compile_landscape_swaps_named_mediabox():
    # Letter landscape MediaBox is 792 x 612.
    pdf = inkmd.compile(SAMPLE, orientation="landscape")
    assert mediabox(pdf) == ("792", "612")


def test_compile_landscape_swaps_custom_mediabox():
    pdf = inkmd.compile(
        SAMPLE, layout=LayoutConfig(page_size=(400, 600), orientation="landscape")
    )
    assert mediabox(pdf) == ("600.0", "400.0")


def test_compile_portrait_is_default_unchanged():
    portrait = inkmd.compile(SAMPLE)
    explicit = inkmd.compile(SAMPLE, orientation="portrait")
    assert portrait == explicit
    assert mediabox(portrait) == ("612", "792")


def test_compile_invalid_orientation_raises_valueerror():
    with pytest.raises(ValueError):
        inkmd.compile(SAMPLE, orientation="sideways")


# --- compile(): landscape gives a wider content column ---------------------


def _body_line_count(md: str, orientation: str) -> tuple[float, int]:
    """Resolve the column for ``orientation`` and paginate ``md`` the same way
    ``compile`` does, returning (content_width, total positioned text lines)."""
    from inkmd.parser import parse
    from inkmd.render import render_document, FAMILIES
    from inkmd.layout import paginate_runs, DEFAULT_MARGIN

    w, h = resolve_page_size("letter", orientation)
    content_width = w - 2 * DEFAULT_MARGIN
    doc = parse(md)
    blocks = render_document(
        doc, family=FAMILIES["helvetica"], content_width=content_width
    )
    pages = paginate_runs(blocks, page_width=w, page_height=h, margin=DEFAULT_MARGIN)
    return content_width, sum(len(p.lines) for p in pages)


def test_landscape_widens_content_column():
    long_para = "word " * 120 + "\n"
    portrait_w, portrait_lines = _body_line_count(long_para, "portrait")
    landscape_w, landscape_lines = _body_line_count(long_para, "landscape")
    # The landscape column is wider (letter: 648pt vs 468pt) ...
    assert landscape_w > portrait_w
    # ... so the same paragraph wraps into strictly fewer lines.
    assert landscape_lines < portrait_lines


def test_landscape_output_differs_from_portrait():
    wide_table = (
        "| A | B | C | D | E | F |\n"
        "|---|---|---|---|---|---|\n"
        "| one | two | three | four | five | six |\n"
    )
    md = "# Wide table\n\n" + wide_table
    assert inkmd.compile(md) != inkmd.compile(md, orientation="landscape")


# --- flat overrides win over layout= ---------------------------------------


def test_flat_page_size_wins_over_layout():
    pdf = inkmd.compile(SAMPLE, layout=LayoutConfig(page_size="a3"), page_size="a5")
    assert mediabox(pdf) == ("420", "595")


def test_flat_orientation_wins_over_layout():
    pdf = inkmd.compile(
        SAMPLE,
        layout=LayoutConfig(orientation="portrait"),
        orientation="landscape",
    )
    assert mediabox(pdf) == ("792", "612")


def test_flat_page_size_string_works_as_flat_arg():
    assert mediabox(inkmd.compile(SAMPLE, page_size="a3")) == ("842", "1191")


# --- the existing KeyError contract is preserved ---------------------------


def test_compile_unknown_name_still_raises_keyerror():
    with pytest.raises(KeyError):
        inkmd.compile(SAMPLE, page_size="foolscap")


def test_compile_a4_unchanged_then_unknown_raises():
    # The existing exact spelling still resolves ...
    assert mediabox(inkmd.compile(SAMPLE, page_size="A4")) == ("595", "842")
    # ... and a genuinely unknown name still raises KeyError.
    with pytest.raises(KeyError):
        inkmd.compile(SAMPLE, page_size="foolscap")


def test_compile_malformed_custom_size_raises_valueerror():
    with pytest.raises(ValueError):
        inkmd.compile(SAMPLE, layout=LayoutConfig(page_size=(400,)))
    with pytest.raises(ValueError):
        inkmd.compile(SAMPLE, layout=LayoutConfig(page_size=(0, 600)))
