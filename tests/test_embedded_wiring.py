"""Spine 5: live embedded-font wiring + the WinAnsi-boundary run split.

These tests pin S5's integration of S1 (reader) + S2 (measurement) + S3
(emission) into the live ``compile`` path:

* the per-codepoint auto-split (base-14 vs embedded) and attribute
  preservation;
* end-to-end embedding for Cyrillic/Greek, with one shared font;
* the invariant that a pure-ASCII/Latin document embeds NO font;
* the ``font_path=`` override (good + bad);
* the bundled font loads via its packaged asset path (never a system path).
"""

from __future__ import annotations

import re
import zlib

import pytest

import inkmd
from inkmd.cidfont import gid_to_codepoints
from inkmd.embedded import (
    EmbeddedFontRef,
    document_uses_non_winansi,
    is_base14_codepoint,
    load_embedded_font,
    split_run_for_embedding,
)
from inkmd.layout import Run
from inkmd.truetype import TrueTypeFontError


# --- The split predicate --------------------------------------------------


def test_predicate_ascii_and_question_mark_are_base14():
    assert is_base14_codepoint(ord("A"))
    assert is_base14_codepoint(ord("?"))  # literal ? stays base-14
    assert is_base14_codepoint(ord("é"))  # Latin-1, WinAnsi-representable


def test_predicate_cyrillic_greek_are_not_base14():
    assert not is_base14_codepoint(0x041F)  # П
    assert not is_base14_codepoint(0x0395)  # Ε (Greek)
    assert not is_base14_codepoint(0x0100)  # Ā (Latin Extended-A)


# --- Auto-split unit tests ------------------------------------------------


def _ref():
    loaded = load_embedded_font()
    assert loaded is not None
    return EmbeddedFontRef(font=loaded[0], font_bytes=loaded[1])


def test_split_mixed_run_at_boundary_preserving_attrs():
    ref = _ref()
    run = Run(
        text="En Рус",
        font="Helvetica-Bold",
        size=13.0,
        link_url="https://example.com",
        color=(0.1, 0.2, 0.3),
        strike=True,
        y_shift=2.0,
        background_fill=(0.9, 0.9, 0.9),
    )
    pieces = split_run_for_embedding(run, ref)
    assert [p.text for p in pieces] == ["En ", "Рус"]
    base, emb = pieces
    assert base.embedded is None
    assert emb.embedded is ref
    # Every other attribute is preserved on BOTH pieces.
    for p in pieces:
        assert p.font == "Helvetica-Bold"
        assert p.size == 13.0
        assert p.link_url == "https://example.com"
        assert p.color == (0.1, 0.2, 0.3)
        assert p.strike is True
        assert p.y_shift == 2.0
        assert p.background_fill == (0.9, 0.9, 0.9)


def test_split_all_ascii_is_identity():
    ref = _ref()
    run = Run(text="Hello, world!", font="Helvetica", size=12.0)
    pieces = split_run_for_embedding(run, ref)
    assert pieces == [run]  # untouched -> Latin corpus stays byte-identical


def test_split_all_cyrillic_one_embedded_run():
    ref = _ref()
    run = Run(text="Привет", font="Helvetica", size=12.0)
    pieces = split_run_for_embedding(run, ref)
    assert len(pieces) == 1
    assert pieces[0].text == "Привет"
    assert pieces[0].embedded is ref


def test_split_question_mark_literal_stays_base14():
    ref = _ref()
    run = Run(text="why?", font="Helvetica", size=12.0)
    pieces = split_run_for_embedding(run, ref)
    assert pieces == [run]
    assert all(p.embedded is None for p in pieces)


def test_split_alternating_scripts_multiple_spans():
    ref = _ref()
    run = Run(text="aПbГc", font="Helvetica", size=12.0)
    pieces = split_run_for_embedding(run, ref)
    assert [(p.text, p.embedded is ref) for p in pieces] == [
        ("a", False), ("П", True), ("b", False), ("Г", True), ("c", False),
    ]


def test_emoji_run_not_resplit():
    ref = _ref()
    # An emoji run is an image; the split must leave it alone.
    run = Run(text="X", font="Helvetica", size=12.0, emoji=object())  # type: ignore[arg-type]
    assert split_run_for_embedding(run, ref) == [run]


# --- document_uses_non_winansi -------------------------------------------


def test_detect_non_winansi():
    assert document_uses_non_winansi([[Run("Привет", "Helvetica", 12.0)]])
    assert not document_uses_non_winansi([[Run("plain café", "Helvetica", 12.0)]])


# --- End-to-end compile ---------------------------------------------------


def _flate_streams(data: bytes):
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL):
        try:
            yield zlib.decompress(m.group(1))
        except zlib.error:
            continue


def _tounicode_map(data: bytes) -> dict[int, int]:
    """Parse the embedded ToUnicode CMap: GID -> Unicode codepoint."""
    for dec in _flate_streams(data):
        if b"beginbfchar" not in dec:
            continue
        out: dict[int, int] = {}
        # Only the bfchar block, so the codespacerange line isn't captured.
        block = dec.split(b"beginbfchar", 1)[1].split(b"endbfchar", 1)[0]
        for g, u in re.findall(rb"<([0-9A-Fa-f]{4})> <([0-9A-Fa-f]+)>", block):
            out[int(g, 16)] = int(u[:4], 16)
        return out
    return {}


def test_compile_cyrillic_embeds_type0_and_fontfile2():
    data = inkmd.compile("Привет")
    assert data[:4] == b"%PDF"
    assert b"/Subtype /Type0" in data
    assert b"/FontFile2" in data
    assert b"/ToUnicode" in data
    assert b"/FEmb" in data  # the page references the embedded slot


def test_compile_cyrillic_tounicode_roundtrips():
    font, _ = load_embedded_font()
    data = inkmd.compile("Привет")
    cmap = _tounicode_map(data)
    # Every distinct Cyrillic codepoint round-trips through its GID.
    for ch in set("Привет"):
        gid = font.glyph_id(ord(ch))
        assert cmap.get(gid) == ord(ch)


def test_compile_mixed_scripts_one_embedded_font():
    data = inkmd.compile("English Привет Ελληνικά")
    # ONE embedded font carries both scripts.
    assert data.count(b"/Subtype /Type0") == 1
    assert data.count(b"/FontFile2") == 1
    font, _ = load_embedded_font()
    cmap = _tounicode_map(data)
    for ch in set("ПриветΕλληνικά"):
        if ch.isspace():
            continue
        gid = font.glyph_id(ord(ch))
        assert cmap.get(gid) == ord(ch)


def test_pure_latin_document_embeds_no_font():
    # The whole point of the boundary predicate: existing docs untouched.
    data = inkmd.compile("# Hello\n\nA plain Latin paragraph with café & naïve.")
    assert b"/Type0" not in data
    assert b"/FontFile2" not in data
    assert b"/FEmb" not in data


def test_compile_determinism_with_embedding():
    a = inkmd.compile("Привет мир Ελληνικά")
    b = inkmd.compile("Привет мир Ελληνικά")
    assert a == b


# --- font_path= override --------------------------------------------------


def test_font_path_good(tmp_path):
    # Point at the BUNDLED asset (never a system font path).
    import inkmd.embedded as emb
    data = inkmd.compile("Привет", font_path=emb._BUNDLED_FONT)
    assert b"/Subtype /Type0" in data
    assert b"/FontFile2" in data


def test_font_path_bad_raises_clear_error(tmp_path):
    bad = tmp_path / "not-a-font.ttf"
    bad.write_bytes(b"this is not a font")
    with pytest.raises(TrueTypeFontError) as exc:
        inkmd.compile("Привет", font_path=str(bad))
    # A clear message, not a raw struct/parse traceback.
    assert "not-a-font.ttf" in str(exc.value)


def test_font_path_missing_raises_clear_error(tmp_path):
    missing = tmp_path / "does-not-exist.ttf"
    with pytest.raises(TrueTypeFontError) as exc:
        inkmd.compile("Привет", font_path=str(missing))
    assert "does-not-exist.ttf" in str(exc.value)


def test_font_path_ignored_for_latin_only(tmp_path):
    # A bad font_path is irrelevant when the document needs no embedding.
    bad = tmp_path / "junk.ttf"
    bad.write_bytes(b"junk")
    data = inkmd.compile("plain ascii", font_path=str(bad))
    assert b"/Type0" not in data


# --- Bundled font loads via the packaged asset path -----------------------


def test_bundled_font_loads_from_asset_path():
    loaded = load_embedded_font()  # no font_path -> bundled
    assert loaded is not None
    font, font_bytes = loaded
    assert font.units_per_em > 0
    assert font.glyph_id(0x041F) != 0  # П present
    assert font.glyph_id(0x0395) != 0  # Ε present
    assert len(font_bytes) > 0
