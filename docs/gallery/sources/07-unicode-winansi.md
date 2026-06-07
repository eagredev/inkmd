# Unicode, emoji, and the WinAnsi boundary

The 14 base PDF fonts use WinAnsi encoding, a single-byte mapping covering Latin-1 plus extra symbols (em-dash, curly quotes, ellipsis, currency, etc.). Text outside WinAnsi has no glyph in those fonts, so inkmd routes it three ways: **emoji render as color images** (from a bundled font); **Cyrillic, Greek, and Latin-Extended render through an embedded font**; and a codepoint no available font covers (e.g. CJK, which the bundled font lacks) shows a visible `[U+XXXX]` marker rather than a silent `?`. This gallery shows what each path looks like.

## Always available

ASCII printable: !"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyz{|}~

## WinAnsi extras

Em dash: — (U+2014). En dash: – (U+2013). Curly quotes: "double" and 'single'. Ellipsis: … (U+2026). Bullet: • (U+2022). Dagger: † (U+2020). Double dagger: ‡ (U+2021). Per mille: ‰ (U+2030). Trademark: ™. Registered: ®. Copyright: ©. Section: §. Paragraph: ¶.

Currency symbols in WinAnsi: $ £ ¥ ¤ ¢ €. Fractions: ½ ¼ ¾. Plus: ± × ÷.

Accented Latin: é è ê ë ñ ç ü ö ä Å Æ Ø ß ÿ.

## Emoji (render as color images)

Single emoji: 🎉 🚀 ✅ ⚠️ 🔥 💡 📦. Skin tone: 👍🏽. Flags: 🇯🇵 🇺🇸 🇬🇧. ZWJ sequences: 👨‍👩‍👧 (family) and 🏳️‍🌈 (rainbow flag). Keycaps: 0️⃣ 1️⃣ 5️⃣ #️⃣.

Emoji are drawn from a bundled color font as small inline images scaled to the surrounding text size. They look crisp inline; at very large heading sizes the bitmaps soften slightly (a documented trade-off of the bitmap approach). The single-file zipapp build omits the font and falls back to a textual label such as `[rocket]`.

## Outside WinAnsi (embedded font or `[U+XXXX]` marker)

Cyrillic, Greek, and Latin-Extended render through the embedded font. A codepoint no available font covers (CJK under the bundled font) shows a visible `[U+XXXX]` marker, and inkmd emits a `MissingGlyphWarning`. CJK full rendering is a planned later font pack.

Cyrillic: Привет, мир.

Greek: αβγδε ΑΒΓΔΕ, and a Δ (capital delta) by itself.

CJK (shows `[U+XXXX]` markers, the bundled font has no CJK): 你好世界 (Chinese), こんにちは世界 (Japanese hiragana), 안녕하세요 (Korean).

Mathematical: ∑ ∫ √ ∞ ≠ ≤ ≥ ∈ ∀ ∃.

Arrows: → ← ↑ ↓ ⇒ ⇐ ⇔ ↕.

## Mixed inline

A paragraph that mixes Latin, emoji, and other scripts: "Hello, bonjour, guten Tag, 🌍, Привет, 你好". The Latin parts and the emoji render directly; the Cyrillic renders through the embedded font; and the CJK, which the bundled font does not cover, shows `[U+XXXX]` markers. inkmd splits the line per codepoint to route each one.

## In code blocks

```
ASCII only: works.
Em dash —: works (WinAnsi).
Emoji 🚀: renders as a color image.
Delta Δ: renders via the embedded font.
```

```
A Python literal with Unicode:
greeting = "Привет, мир"
```

## In tables

Embedded-font routing does not yet reach table cells: the column widths are computed before the run split, so non-WinAnsi text inside a cell still renders `?` (a known limitation, fix pending). The same text in prose renders through the embedded font, as the Cyrillic line above shows.

| Region | Greeting | Status |
|--------|----------|--------|
| English | Hello | OK |
| French | Bonjour | OK |
| Emoji | 🚀 | renders |
| Russian | Привет | `?` |
| Chinese | 你好 | `?` |
