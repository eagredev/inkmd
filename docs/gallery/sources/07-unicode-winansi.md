# Unicode and WinAnsi boundary

The 14 base PDF fonts use WinAnsi encoding — a single-byte mapping covering Latin-1 plus extra symbols (em-dash, curly quotes, ellipsis, currency, etc.). Any codepoint outside WinAnsi renders as `?` in v0.1. This gallery shows what's in scope and what falls off the edge.

## Always available

ASCII printable: !"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\]^_`abcdefghijklmnopqrstuvwxyz{|}~

## WinAnsi extras

Em dash: — (U+2014). En dash: – (U+2013). Curly quotes: "double" and 'single'. Ellipsis: … (U+2026). Bullet: • (U+2022). Dagger: † (U+2020). Double dagger: ‡ (U+2021). Per mille: ‰ (U+2030). Trademark: ™. Registered: ®. Copyright: ©. Section: §. Paragraph: ¶.

Currency symbols in WinAnsi: $ £ ¥ ¤ ¢ €. Fractions: ½ ¼ ¾. Plus: ± × ÷.

Accented Latin: é è ê ë ñ ç ü ö ä Å Æ Ø ß ÿ.

## Outside WinAnsi (will render as `?` in v0.1)

These are documented as v0.1 limitations; v0.2 font embedding lifts the restriction.

Cyrillic: Привет, мир.

Greek: αβγδε ΑΒΓΔΕ — and a Δ (capital delta) by itself.

CJK: 你好世界 (Chinese), こんにちは世界 (Japanese hiragana), 안녕하세요 (Korean).

Emoji: 🦅 (bird, the inkmd mascot if we had one). Also 🎉, 🚀, ✅, ⚠️.

Mathematical: ∑ ∫ √ ∞ ≠ ≤ ≥ ∈ ∀ ∃.

Arrows: → ← ↑ ↓ ⇒ ⇐ ⇔ ↕.

## Mixed inline

A paragraph that mixes Latin and non-Latin: "Hello — bonjour — guten Tag — Привет — 你好 — مرحبا — 🌍". Expect the Latin parts to render correctly and the non-Latin parts to fall back to `?`.

## In code blocks

```
ASCII only: works.
Em dash —: works (WinAnsi).
Delta Δ: shows as ? in v0.1.
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
| Russian | Привет | `?` in v0.1 |
| Chinese | 你好 | `?` in v0.1 |
