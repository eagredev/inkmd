"""LayoutConfig and the flat-override folding layer (v0.5 S0).

S0 introduces the public ``LayoutConfig`` and wires ``compile`` /
``render_file`` to accept it plus flat keyword overrides, with ZERO
rendering change. These tests pin the config shape, the fold precedence
(flat override wins over the config's value), and byte-identity between
the no-config and default-config call forms. The frozen validation
baseline proves byte-identity against actual v0.4 output; here we prove
the two API forms agree and the fold resolves correctly.
"""

from __future__ import annotations

import dataclasses

import pytest

import inkmd
from inkmd import LayoutConfig
from inkmd.layout import fold_layout, _UNSET


# A spread that exercises headings, body, emphasis, a list, code, and a
# table so byte-identity covers more than one code path.
SPREAD = (
    "# Heading\n\n"
    "Body with **bold** and *italic* and `code`.\n\n"
    "- one\n- two\n- three\n\n"
    "```\nblock code\n```\n\n"
    "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
    "A rocket \U0001f680 and an accent café.\n"
)


# --- Config shape ---------------------------------------------------------


def test_default_field_values():
    cfg = LayoutConfig()
    assert cfg.page_size == "letter"
    assert cfg.margin == 72.0
    assert cfg.font_size == 12.0
    assert cfg.line_spacing == 1.2


def test_is_frozen():
    cfg = LayoutConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.margin = 54.0  # type: ignore[misc]


def test_is_hashable():
    cfg = LayoutConfig()
    # Hashable means it can live in a set / be a dict key.
    assert hash(cfg) == hash(LayoutConfig())
    assert {cfg} == {LayoutConfig()}


def test_equality_by_value():
    assert LayoutConfig(margin=54) == LayoutConfig(margin=54)
    assert LayoutConfig(margin=54) != LayoutConfig(margin=55)


def test_replace_produces_new_config():
    base = LayoutConfig()
    derived = dataclasses.replace(base, margin=54)
    assert base.margin == 72.0  # untouched
    assert derived.margin == 54.0
    assert derived.font_size == 12.0  # other fields carried over


def test_exported_from_package():
    assert "LayoutConfig" in inkmd.__all__
    assert inkmd.LayoutConfig is LayoutConfig


# --- Fold precedence (flat override wins) ---------------------------------


def _all_unset() -> dict[str, object]:
    return {
        "page_size": _UNSET,
        "margin": _UNSET,
        "font_size": _UNSET,
        "line_spacing": _UNSET,
    }


def test_fold_none_layout_no_overrides_is_default():
    assert fold_layout(None, _all_unset()) == LayoutConfig()


def test_fold_returns_supplied_layout_when_no_overrides():
    house = LayoutConfig(margin=54, font_size=11)
    assert fold_layout(house, _all_unset()) == house


def test_fold_flat_override_wins_over_layout():
    house = LayoutConfig(margin=54, font_size=11)
    over = _all_unset()
    over["margin"] = 72
    eff = fold_layout(house, over)
    assert eff.margin == 72  # flat wins
    assert eff.font_size == 11  # untouched field rides the config


def test_fold_flat_override_on_default_config():
    over = _all_unset()
    over["margin"] = 54
    eff = fold_layout(None, over)
    assert eff.margin == 54
    assert eff.font_size == 12.0  # otherwise default
    assert eff.page_size == "letter"


def test_fold_multiple_overrides():
    over = _all_unset()
    over["margin"] = 36
    over["line_spacing"] = 1.5
    eff = fold_layout(LayoutConfig(font_size=10), over)
    assert eff.margin == 36
    assert eff.line_spacing == 1.5
    assert eff.font_size == 10  # from the config, not overridden


def test_fold_unset_sentinel_is_not_a_value():
    # Passing the sentinel must be treated as "omitted", never folded in.
    eff = fold_layout(LayoutConfig(margin=54), {"margin": _UNSET})
    assert eff.margin == 54


# --- Byte-identity between call forms (S0 ships no rendering change) -------


def test_no_config_equals_default_config():
    assert inkmd.compile(SPREAD) == inkmd.compile(SPREAD, layout=LayoutConfig())


def test_explicit_default_flat_args_equal_no_args():
    # Passing the documented default values as flat args must match passing
    # nothing: the fold replaces with the same values, so output is identical.
    explicit = inkmd.compile(
        SPREAD, margin=72.0, font_size=12.0, line_spacing=1.2
    )
    assert explicit == inkmd.compile(SPREAD)


@pytest.mark.parametrize(
    "md",
    [
        "",
        "Plain paragraph.",
        "# Just a heading",
        "A non-Latin line: русский.",
        "Emoji only: \U0001f600\U0001f389\U0001f680",
    ],
)
def test_no_config_equals_default_config_spread(md):
    assert inkmd.compile(md) == inkmd.compile(md, layout=LayoutConfig())


# --- page_size folds into the same precedence model -----------------------


def test_page_size_flat_and_layout_agree():
    flat = inkmd.compile(SPREAD, page_size="A4")
    grouped = inkmd.compile(SPREAD, layout=LayoutConfig(page_size="A4"))
    assert flat == grouped


def test_page_size_positional_still_binds():
    assert inkmd.compile(SPREAD, "A4") == inkmd.compile(SPREAD, page_size="A4")


def test_page_size_flat_wins_over_layout():
    # layout says A4, flat says letter -> flat (letter) governs.
    flat_letter = inkmd.compile(
        SPREAD, page_size="letter", layout=LayoutConfig(page_size="A4")
    )
    assert flat_letter == inkmd.compile(SPREAD, page_size="letter")


def test_a4_differs_from_letter():
    # Sanity: the page_size knob actually changes output, so the agreement
    # tests above are meaningful rather than vacuous.
    assert inkmd.compile(SPREAD, page_size="A4") != inkmd.compile(SPREAD)


def test_unknown_page_size_still_raises_keyerror():
    with pytest.raises(KeyError):
        inkmd.compile(SPREAD, page_size="B5")


def test_unknown_page_size_via_layout_still_raises_keyerror():
    with pytest.raises(KeyError):
        inkmd.compile(SPREAD, layout=LayoutConfig(page_size="B5"))


# --- render_file accepts the same options ---------------------------------


def test_render_file_accepts_layout_and_flat_args(tmp_path):
    src = tmp_path / "in.md"
    src.write_text(SPREAD, encoding="utf-8")

    out_default = tmp_path / "default.pdf"
    out_layout = tmp_path / "layout.pdf"
    out_flat = tmp_path / "flat.pdf"

    inkmd.render_file(src, out_default)
    inkmd.render_file(src, out_layout, layout=LayoutConfig())
    inkmd.render_file(src, out_flat, margin=72.0, font_size=12.0, line_spacing=1.2)

    a = out_default.read_bytes()
    assert a == out_layout.read_bytes()
    assert a == out_flat.read_bytes()
    # And matches compile() on the same source (render_file sets base_dir to
    # the file's parent; with no images that does not change bytes here).
    assert a == inkmd.compile(SPREAD, base_dir=src.parent)


def test_render_file_page_size_flat_and_layout_agree(tmp_path):
    src = tmp_path / "in.md"
    src.write_text(SPREAD, encoding="utf-8")
    flat = tmp_path / "flat.pdf"
    grouped = tmp_path / "grouped.pdf"
    inkmd.render_file(src, flat, page_size="A4")
    inkmd.render_file(src, grouped, layout=LayoutConfig(page_size="A4"))
    assert flat.read_bytes() == grouped.read_bytes()
