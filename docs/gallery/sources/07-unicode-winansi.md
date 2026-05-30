# Unicode, emoji, and the WinAnsi boundary

The 14 base PDF fonts use WinAnsi encoding — a single-byte mapping covering Latin-1 plus extra symbols (em-dash, curly quotes, ellipsis, currency, etc.). Text outside WinAnsi has no glyph in those fonts. inkmd handles the edge in two ways: **emoji render as color images** (from a bundled font), while other non-Latin scripts (CJK, Cyrillic, Greek, …) currently fall back to `?`. This gallery shows what's in scope and what falls off the edge.

## Always available

ASCII printable: !"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyz{|}~

## WinAnsi extras

Em dash: — (U+2014). En dash: – (U+2013). Curly quotes: "double" and 'single'. Ellipsis: … (U+2026). Bullet: • (U+2022). Dagger: † (U+2020). Double dagger: ‡ (U+2021). Per mille: ‰ (U+2030). Trademark: ™. Registered: ®. Copyright: ©. Section: §. Paragraph: ¶.

Currency symbols in WinAnsi: $ £ ¥ ¤ ¢ €. Fractions: ½ ¼ ¾. Plus: ± × ÷.

Accented Latin: é è ê ë ñ ç ü ö ä Å Æ Ø ß ÿ.

## Emoji (render as color images)

Single emoji: 🎉 🚀 ✅ ⚠️ 🔥 💡 📦. Skin tone: 👍🏽. Flags: 🇯🇵 🇺🇸 🇬🇧. ZWJ sequences: 👨‍👩‍👧 (family) and 🏳️‍🌈 (rainbow flag). Keycaps: 0️⃣ 1️⃣ 5️⃣ #️⃣.

Emoji are drawn from a bundled color font as small inline images scaled to the surrounding text size. They look crisp inline; at very large heading sizes the bitmaps soften slightly (a documented trade-off of the bitmap approach). The single-file zipapp build omits the font and falls back to a textual label such as `[rocket]`.

## Outside WinAnsi (still render as `?`)

Scripts other than emoji are documented limitations; full text-font embedding would lift them in a later release.

Cyrillic: Привет, мир.

Greek: αβγδε ΑΒΓΔΕ — and a Δ (capital delta) by itself.

CJK: 你好世界 (Chinese), こんにちは世界 (Japanese hiragana), 안녕하세요 (Korean).

Mathematical: ∑ ∫ √ ∞ ≠ ≤ ≥ ∈ ∀ ∃.

Arrows: → ← ↑ ↓ ⇒ ⇐ ⇔ ↕.

## Mixed inline

A paragraph that mixes Latin, emoji, and other scripts: "Hello — bonjour — guten Tag — 🌍 — Привет — 你好 — مرحبا". Expect the Latin parts and the emoji to render correctly, and the remaining non-Latin scripts to fall back to `?`.

## In code blocks

```
ASCII only: works.
Em dash —: works (WinAnsi).
Emoji 🚀: renders as a color image.
Delta Δ: shows as ?.
```

```
A Python literal with Unicode:
greeting = "Привет, мир"
```

## In tables

| Region | Greeting | Status |
|--------|----------|--------|
| English | Hello | OK |
| French | Bonjour | OK |
| Emoji | 🚀 | renders |
| Russian | Привет | `?` |
| Chinese | 你好 | `?` |
