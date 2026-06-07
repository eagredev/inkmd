"""Unicode NFC normalization at ingestion (v0.4 / Stream S4).

Markdown can arrive decomposed (NFD): ``café`` as base ``e`` + U+0301
combining acute, instead of the single codepoint U+00E9. The WinAnsi
encoder maps the combining acute to byte 0x3F = ``?``, so NFD ``café``
would render as ``cafe?``. inkmd normalizes the whole markdown string to
NFC in :func:`inkmd.compile` (before parsing), composing decomposed
sequences to their single-codepoint form so the WinAnsi path renders them.

These tests pin:
- the headline fix (NFD café -> composed U+00E9 byte 0xE9, not 0x3F ``?``),
- that already-NFC / ASCII input is a no-op,
- that code blocks are composed too (the deliberate whole-string-NFC choice),
- that NFC is used, NOT NFKC (a compatibility char passes through unchanged),
- that :func:`inkmd.render_file` inherits the fix via :func:`inkmd.compile`.
"""

from __future__ import annotations

import unicodedata
import unicodedata as _ud
from pathlib import Path

import inkmd
from inkmd.fonts import to_winansi_byte


# Building blocks for the headline case.
NFD_CAFE = "café"  # c a f e + COMBINING ACUTE ACCENT (U+0301)
NFC_CAFE = "café"  # c a f é (PRECOMPOSED LATIN SMALL E WITH ACUTE)


def test_winansi_byte_premise():
    """Premise check: the combining acute drops to '?', composed é does not.

    This is the corruption S4 exists to prevent; if these mappings ever
    change, the headline test's rationale needs revisiting.
    """
    assert to_winansi_byte(0x0301) == ord("?") == 0x3F
    assert to_winansi_byte(0x00E9) == 0xE9 == 233


def test_nfd_cafe_renders_composed_byte():
    """Headline fix: NFD ``café`` composes to U+00E9 and emits byte 0xE9.

    The combining-acute byte (0x3F '?') must NOT be how é is encoded. The
    content stream is uncompressed, so the WinAnsi byte appears directly.
    """
    assert NFD_CAFE != NFC_CAFE  # genuinely decomposed input
    data = inkmd.compile(NFD_CAFE)
    assert b"\xe9" in data  # é as the single WinAnsi byte 0xE9
    # The 'cafe?' corruption would leave the literal 'cafe?' run in a Tj
    # string; the composed run is 'café' (caf + 0xE9). Pin that 'caf?' (the
    # decomposed tail with the dropped combining mark) is absent.
    assert b"caf?" not in data


def test_nfd_and_nfc_cafe_render_identically():
    """NFD and NFC café produce byte-identical PDFs after normalization."""
    assert inkmd.compile(NFD_CAFE) == inkmd.compile(NFC_CAFE)


def test_ascii_input_is_noop():
    """Pure-ASCII input is unchanged by NFC; output is stable."""
    text = "hello world"
    assert unicodedata.normalize("NFC", text) == text  # NFC no-op on ASCII
    # Two compiles of ASCII input agree (determinism / no surprise from NFC).
    assert inkmd.compile(text) == inkmd.compile(text)


def test_already_nfc_input_is_noop():
    """Already-composed input is a no-op: NFC is idempotent."""
    assert unicodedata.normalize("NFC", NFC_CAFE) == NFC_CAFE
    # Compiling already-NFC text twice is identical (idempotence at scale is
    # what the baseline gate proves on the real corpus).
    assert inkmd.compile(NFC_CAFE) == inkmd.compile(NFC_CAFE)


def test_code_block_is_composed_too():
    """A fenced code block with an NFD sequence is composed (deliberate).

    Whole-string NFC at ingestion composes code too. This is the intended
    behaviour (a code block holding a genuinely-decomposed sequence for
    display is vanishingly rare and out of S4 scope), not a regression.
    """
    nfd_in_code = f"```\n{NFD_CAFE}\n```\n"
    data = inkmd.compile(nfd_in_code)
    assert b"\xe9" in data  # the é inside the code block is composed -> 0xE9
    # Byte-identical to the composed-source version of the same code block.
    nfc_in_code = f"```\n{NFC_CAFE}\n```\n"
    assert inkmd.compile(nfd_in_code) == inkmd.compile(nfc_in_code)


def test_nfc_not_nfkc_ligature():
    """REGRESSION GUARD: the 'fi' ligature (U+FB01) survives NFC unchanged.

    NFKC would decompose U+FB01 to 'f' + 'i'. NFC must not. This pins that
    S4 uses canonical (NFC) and not compatibility (NFKC) normalization --
    NFKC would change which abstract characters the author wrote.
    """
    fi = "ﬁ"  # LATIN SMALL LIGATURE FI
    assert _ud.normalize("NFC", fi) == fi  # NFC leaves it alone
    assert _ud.normalize("NFKC", fi) == "fi"  # NFKC would NOT -- the bug we avoid
    # Compiling the ligature must not turn it into 'fi'; the ligature is not a
    # WinAnsi glyph so it renders as the '?' fallback, but it must remain ONE
    # character, never be expanded to two by the normalizer.
    data = inkmd.compile(fi)
    assert b"fi" not in data  # not split into f + i (would betray NFKC)


def test_nfc_not_nfkc_superscript():
    """REGRESSION GUARD: superscript-two (U+00B2) survives NFC unchanged.

    NFKC would rewrite U+00B2 to the digit '2'. NFC must not.
    """
    sup2 = "²"  # SUPERSCRIPT TWO
    assert _ud.normalize("NFC", sup2) == sup2  # NFC leaves it alone
    assert _ud.normalize("NFKC", sup2) == "2"  # NFKC would rewrite it -- avoided
    data = inkmd.compile(sup2)
    # U+00B2 is in the Latin-1 upper half (WinAnsi byte 0xB2); it must be
    # rendered as itself, never rewritten to the ASCII digit '2' by the
    # normalizer.
    assert b"\xb2" in data


def test_render_file_inherits_normalization(tmp_path: Path):
    """render_file routes through compile, so it inherits the NFC fix.

    render_file reads the file as UTF-8 and calls compile(); it has no
    separate parse path, so the NFD café written to disk composes the same
    way it does for compile().
    """
    md_path = tmp_path / "in.md"
    pdf_path = tmp_path / "out.pdf"
    md_path.write_text(NFD_CAFE + "\n", encoding="utf-8")
    inkmd.render_file(md_path, pdf_path)
    data = pdf_path.read_bytes()
    assert b"\xe9" in data  # composed é via the inherited normalization
