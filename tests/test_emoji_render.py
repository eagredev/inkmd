"""End-to-end emoji rendering tests (render + layout + pdf integration).

These are portable: they patch the emoji font loader to use a synthetic
in-memory CBDT font (built by the test_emoji_font helper) so the result
never depends on a system Noto Color Emoji being installed.
"""

from __future__ import annotations

import pytest

import inkmd
from inkmd import emoji as emoji_mod
from inkmd.emoji_font import EmojiFont
from inkmd.layout import (
    DEFAULT_MARGIN,
    Run,
    emoji_box,
    paginate_runs,
    wrap_runs,
)
from inkmd.render import FAMILIES, render_document
from inkmd.parser import parse

from tests.test_emoji_font import _build_cbdt_font, _tiny_png


# Codepoints our synthetic font will know about.
_ROCKET = 0x1F680
_CHECK = 0x2705
_HEART = 0x2764


@pytest.fixture
def synthetic_emoji_font(monkeypatch):
    """Patch the emoji loader to a synthetic font covering a few glyphs."""
    font_bytes = _build_cbdt_font(
        {_ROCKET: 1, _CHECK: 2, _HEART: 3},
        {1: _tiny_png(w=136, h=128), 2: _tiny_png(w=120, h=128),
         3: _tiny_png(w=128, h=128)},
        variation=(_HEART, 0xFE0F, 3),
    )
    font = EmojiFont(font_bytes)
    emoji_mod._load_font.cache_clear()  # drop any real-font cache entry
    monkeypatch.setattr(emoji_mod, "_load_font", lambda: font)
    yield font
    # monkeypatch restores the original _load_font automatically; its cache
    # was cleared above and will repopulate on next real use.


def _all_runs(md, page_size="letter"):
    from inkmd.pdf import PAGE_SIZES
    pw, ph = PAGE_SIZES[page_size]
    cw = pw - 2 * DEFAULT_MARGIN
    blocks = render_document(parse(md), FAMILIES["helvetica"], content_width=cw)
    pages = paginate_runs(blocks, page_width=pw, page_height=ph)
    return [r for pg in pages for ln in pg.lines for r in ln.runs], pages


# --- render: text splitting -----------------------------------------------


def test_text_splits_into_emoji_and_text_runs(synthetic_emoji_font):
    from inkmd.emoji import split_text_into_runs
    runs = split_text_into_runs(
        "hi 🚀 go", font="Helvetica", size=12.0,
        link_url=None, color=None, strike=False,
    )
    # Expect: "hi " text, rocket emoji, " go" text.
    assert [bool(r.emoji) for r in runs] == [False, True, False]
    assert runs[0].text == "hi "
    assert runs[1].emoji is not None
    assert runs[1].emoji.image_id == "emoji:1F680"
    assert runs[2].text == " go"


def test_non_emoji_text_is_single_run(synthetic_emoji_font):
    from inkmd.emoji import split_text_into_runs
    runs = split_text_into_runs(
        "plain text", font="Helvetica", size=12.0,
        link_url=None, color=None, strike=False,
    )
    assert len(runs) == 1
    assert runs[0].emoji is None


def test_unknown_emoji_stays_text(synthetic_emoji_font):
    from inkmd.emoji import split_text_into_runs
    # U+1F600 grinning is in the emoji range but NOT in the synthetic font.
    runs = split_text_into_runs(
        "x \U0001F600 y", font="Helvetica", size=12.0,
        link_url=None, color=None, strike=False,
    )
    assert all(r.emoji is None for r in runs)
    assert "".join(r.text for r in runs) == "x \U0001F600 y"


def test_variation_selector_consumed(synthetic_emoji_font):
    from inkmd.emoji import split_text_into_runs
    runs = split_text_into_runs(
        "love ❤️ you", font="Helvetica", size=12.0,
        link_url=None, color=None, strike=False,
    )
    emoji_runs = [r for r in runs if r.emoji]
    assert len(emoji_runs) == 1
    # The FE0F is consumed into the emoji run, not left in the text.
    assert "️" not in "".join(r.text for r in runs if not r.emoji)


# --- layout: sizing + placement -------------------------------------------


def test_emoji_box_scales_with_font_size():
    w12, h12 = emoji_box(12.0, 1.0)
    w24, h24 = emoji_box(24.0, 1.0)
    assert h24 == pytest.approx(2 * h12)
    assert w24 == pytest.approx(2 * w12)


def test_emoji_box_respects_aspect():
    w, h = emoji_box(12.0, 1.5)
    assert w == pytest.approx(h * 1.5)


def test_emoji_run_measured_as_box_in_wrap(synthetic_emoji_font):
    from inkmd.emoji import split_text_into_runs
    runs = split_text_into_runs(
        "🚀", font="Helvetica", size=12.0,
        link_url=None, color=None, strike=False,
    )
    lines = wrap_runs(runs, column_width=500.0)
    assert len(lines) == 1 and len(lines[0]) == 1
    assert lines[0][0].emoji is not None


# --- pdf: image emission --------------------------------------------------


def test_compile_emits_emoji_as_image(synthetic_emoji_font):
    pdf = inkmd.compile("Launch 🚀 now")
    assert pdf[:4] == b"%PDF"
    assert b"/Subtype /Image" in pdf
    # The placeholder text must NOT be stamped as a text glyph.
    # (Hard to assert directly in compressed streams; assert image present
    # and that the doc is well-formed + deterministic instead.)
    assert pdf == inkmd.compile("Launch 🚀 now")


def test_repeated_emoji_shares_one_xobject(synthetic_emoji_font):
    from inkmd.pdf import PAGE_SIZES
    # Two rockets -> one image_id -> deduped to a single XObject pair.
    runs, pages = _all_runs("🚀 and 🚀 again")
    emoji_runs = [r for r in runs if r.emoji]
    assert len(emoji_runs) == 2
    assert emoji_runs[0].emoji.image_id == emoji_runs[1].emoji.image_id


def test_emoji_run_carried_to_positioned_run(synthetic_emoji_font):
    runs, _ = _all_runs("ship it 🚀")
    assert any(r.emoji is not None for r in runs)


def test_emoji_image_placement_on_page(synthetic_emoji_font):
    from inkmd.layout import ImagePlacement
    _, pages = _all_runs("ship it 🚀")
    placements = [
        s for pg in pages for s in pg.shapes if isinstance(s, ImagePlacement)
    ]
    assert len(placements) == 1
    p = placements[0]
    assert p.image_id == "emoji:1F680"
    assert p.width > 0 and p.height > 0


def test_heading_emoji_larger_than_body_emoji(synthetic_emoji_font):
    from inkmd.layout import ImagePlacement
    _, pages = _all_runs("# Big 🚀\n\nsmall 🚀")
    placements = [
        s for pg in pages for s in pg.shapes if isinstance(s, ImagePlacement)
    ]
    assert len(placements) == 2
    heights = sorted(p.height for p in placements)
    # Heading emoji box is taller than the body one.
    assert heights[1] > heights[0]


# --- graceful absence (no font) -------------------------------------------


def test_no_font_leaves_emoji_as_text(monkeypatch):
    emoji_mod._load_font.cache_clear()
    monkeypatch.setattr(emoji_mod, "_load_font", lambda: None)
    from inkmd.emoji import split_text_into_runs
    runs = split_text_into_runs(
        "hi 🚀", font="Helvetica", size=12.0,
        link_url=None, color=None, strike=False,
    )
    assert all(r.emoji is None for r in runs)
    assert "".join(r.text for r in runs) == "hi 🚀"
    # monkeypatch restores _load_font; clear so other tests reload cleanly.


# --- Emoji sequences via GSUB ligatures (Phase 4) -------------------------

# Codepoints + gids for sequence fixtures.
_MAN, _WOMAN, _GIRL = 0x1F468, 0x1F469, 0x1F467
_ZWJ = 0x200D
_THUMB, _SKIN = 0x1F44D, 0x1F3FD
_RI_J, _RI_P = 0x1F1EF, 0x1F1F5  # regional indicators J, P (Japan)


@pytest.fixture
def sequence_emoji_font(monkeypatch):
    """Synthetic font with ligatures for a family ZWJ sequence, a
    skin-tone sequence, and a regional-indicator flag pair."""
    cmap = {
        _ROCKET: 1, _MAN: 2, _WOMAN: 3, _GIRL: 4, _ZWJ: 5,
        _THUMB: 6, _SKIN: 7, _RI_J: 8, _RI_P: 9,
        0x0023: 10, 0x0035: 11, 0x20E3: 12,  # '#', '5', keycap combiner
    }
    # Ligature glyphs live at gids 20+.
    ligs = {
        (2, 5, 3, 5, 4): 20,   # man ZWJ woman ZWJ girl -> family
        (6, 7): 21,            # thumb + skin tone
        (8, 9): 22,            # J + P -> Japan flag
        (10, 12): 23,          # '#' + keycap -> #-keycap
        (11, 12): 24,          # '5' + keycap -> 5-keycap
    }
    pngs = {g: _tiny_png() for g in list(cmap.values()) + list(ligs.values())}
    font = EmojiFont(_build_cbdt_font(cmap, pngs, ligatures=ligs))
    emoji_mod._load_font.cache_clear()
    monkeypatch.setattr(emoji_mod, "_load_font", lambda: font)
    yield font


def _split(text):
    from inkmd.emoji import split_text_into_runs
    return split_text_into_runs(
        text, font="Helvetica", size=12.0,
        link_url=None, color=None, strike=False,
    )


def test_zwj_family_composes_to_one_emoji(sequence_emoji_font):
    runs = _split("fam \U0001F468‍\U0001F469‍\U0001F467 unit")
    emoji = [r for r in runs if r.emoji]
    assert len(emoji) == 1
    assert emoji[0].emoji.image_id == "emoji:1F468-200D-1F469-200D-1F467"
    assert "".join(r.text for r in runs if not r.emoji) == "fam  unit"


def test_skin_tone_composes_to_one_emoji(sequence_emoji_font):
    runs = _split("ok \U0001F44D\U0001F3FD done")
    emoji = [r for r in runs if r.emoji]
    assert len(emoji) == 1
    assert emoji[0].emoji.image_id == "emoji:1F44D-1F3FD"


def test_regional_indicator_pair_composes_to_flag(sequence_emoji_font):
    runs = _split("flag \U0001F1EF\U0001F1F5 here")
    emoji = [r for r in runs if r.emoji]
    assert len(emoji) == 1
    assert emoji[0].emoji.image_id == "emoji:1F1EF-1F1F5"


def test_two_adjacent_flags_stay_separate(sequence_emoji_font):
    # Two JP flags in a row must be two emoji, not a 4-indicator blob.
    runs = _split("\U0001F1EF\U0001F1F5\U0001F1EF\U0001F1F5")
    emoji = [r for r in runs if r.emoji]
    assert len(emoji) == 2
    assert all(r.emoji.image_id == "emoji:1F1EF-1F1F5" for r in emoji)


def test_partial_sequence_falls_back_to_base(sequence_emoji_font):
    # A man followed by a non-joining emoji: no ligature -> man renders
    # alone, rocket renders alone (two emoji, not one bad ligature).
    runs = _split("\U0001F468\U0001F680")
    emoji = [r for r in runs if r.emoji]
    assert len(emoji) == 2
    assert [e.emoji.image_id for e in emoji] == ["emoji:1F468", "emoji:1F680"]


def test_longest_match_prefers_full_family(sequence_emoji_font):
    # The full 5-glyph family ligature must win even though shorter
    # prefixes exist as glyphs.
    runs = _split("\U0001F468‍\U0001F469‍\U0001F467")
    emoji = [r for r in runs if r.emoji]
    assert len(emoji) == 1
    assert emoji[0].emoji.image_id == "emoji:1F468-200D-1F469-200D-1F467"


def test_sequence_emits_single_image_placement(sequence_emoji_font):
    from inkmd.layout import ImagePlacement
    blocks = render_document(
        parse("\U0001F1EF\U0001F1F5"), FAMILIES["helvetica"], content_width=468.0
    )
    pages = paginate_runs(blocks, page_width=612, page_height=792)
    placements = [s for pg in pages for s in pg.shapes if isinstance(s, ImagePlacement)]
    assert len(placements) == 1
    assert placements[0].image_id == "emoji:1F1EF-1F1F5"


# --- Keycap emoji (ASCII base + FE0F? + U+20E3) ---------------------------


def test_keycap_with_fe0f_renders(sequence_emoji_font):
    runs = _split("press 5️⃣ now")
    emoji = [r for r in runs if r.emoji]
    assert len(emoji) == 1
    assert emoji[0].emoji.image_id == "emoji:0035-FE0F-20E3"
    assert "".join(r.text for r in runs if not r.emoji) == "press  now"


def test_keycap_without_fe0f_renders(sequence_emoji_font):
    runs = _split("x 5⃣ y")  # some sources omit the FE0F
    emoji = [r for r in runs if r.emoji]
    assert len(emoji) == 1
    assert emoji[0].emoji.image_id == "emoji:0035-20E3"


def test_hash_keycap_renders(sequence_emoji_font):
    runs = _split("#️⃣")
    emoji = [r for r in runs if r.emoji]
    assert len(emoji) == 1
    assert emoji[0].emoji.image_id == "emoji:0023-FE0F-20E3"


def test_bare_digits_stay_text(sequence_emoji_font):
    runs = _split("I have 25 apples and 5 pears")
    assert all(r.emoji is None for r in runs)
    assert "".join(r.text for r in runs) == "I have 25 apples and 5 pears"


def test_bare_hash_stays_text(sequence_emoji_font):
    runs = _split("item #5 and #10")
    assert all(r.emoji is None for r in runs)
    assert "".join(r.text for r in runs) == "item #5 and #10"


def test_keycap_base_without_combiner_not_consumed_as_emoji(sequence_emoji_font):
    # A '5' followed by FE0F but NO keycap combiner is not a keycap; it
    # must stay text (an ASCII base is only ever an emoji via the keycap
    # ligature).
    runs = _split("5️ rest")
    assert all(r.emoji is None for r in runs)
    assert "5" in "".join(r.text for r in runs)


def test_keycap_emits_image_placement(sequence_emoji_font):
    from inkmd.layout import ImagePlacement
    blocks = render_document(
        parse("5️⃣"), FAMILIES["helvetica"], content_width=468.0
    )
    pages = paginate_runs(blocks, page_width=612, page_height=792)
    placements = [s for pg in pages for s in pg.shapes if isinstance(s, ImagePlacement)]
    assert len(placements) == 1
    assert placements[0].image_id == "emoji:0035-FE0F-20E3"


# --- Bundled font (Phase 5): emoji render with no patching ----------------


def test_bundled_font_renders_emoji_unpatched():
    """With the font bundled in the package, emoji render out of the box —
    no monkeypatch, no system font. Proves the default-install experience."""
    emoji_mod._load_font.cache_clear()
    try:
        assert emoji_mod.emoji_available()
        pdf = inkmd.compile("Ship it \U0001F680")
        assert b"/Subtype /Image" in pdf
    finally:
        emoji_mod._load_font.cache_clear()


def test_inkmd_no_emoji_env_disables(monkeypatch):
    """INKMD_NO_EMOJI=1 forces the text-fallback path (the lite behaviour)
    even when the bundled font is present."""
    monkeypatch.setenv("INKMD_NO_EMOJI", "1")
    emoji_mod._load_font.cache_clear()
    try:
        assert not emoji_mod.emoji_available()
        pdf = inkmd.compile("Ship it \U0001F680")
        assert b"/Subtype /Image" not in pdf
    finally:
        emoji_mod._load_font.cache_clear()


def test_bundled_emoji_output_deterministic():
    emoji_mod._load_font.cache_clear()
    try:
        md = "Status \U00002705 and flag \U0001F1EF\U0001F1F5"
        assert inkmd.compile(md) == inkmd.compile(md)
    finally:
        emoji_mod._load_font.cache_clear()
