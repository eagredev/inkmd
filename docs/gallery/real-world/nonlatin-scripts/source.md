# Non-Latin scripts

inkmd embeds a font for text the 14 base PDF fonts cannot represent. Cyrillic, Greek, and Latin-Extended render through the bundled DejaVuSans (or any TrueType font passed with `font_path=`). A codepoint no available font covers shows a visible `[U+XXXX]` marker rather than a silent `?`, and inkmd emits a warning so the gap is machine-detectable.

## Scripts the bundled font covers

These lines render as real glyphs, selectable and copyable from the PDF.

- Russian (Cyrillic): Здравствуйте, мир. Числа 2026 и знаки препинания.
- Ukrainian (Cyrillic): Привіт, світе. Ґанок, їжак, юшка.
- Greek: Γειά σου, κόσμε. Τόνοι και διαλυτικά: προϊόν, γάιδαρος.
- Polish (Latin-Extended): Zażółć gęślą jaźń.
- Czech (Latin-Extended): Příliš žluťoučký kůň úpěl ďábelské ódy.
- Turkish (Latin-Extended): İstanbul, ğ, ş, ı, ç, ö, ü.
- Vietnamese (Latin-Extended): Tiếng Việt rất đẹp và phong phú.

### A note on tables

Embedded-font routing does not yet reach table cells: column widths are computed before the run split, so non-WinAnsi text inside a cell still renders `?` (a known limitation, fix pending). The same names render correctly in the prose list above.

| Script | Sample in a cell | Result |
|--------|------------------|--------|
| Cyrillic | Москва | renders `?` (table-cell limitation) |
| Greek | Αθήνα | renders `?` (table-cell limitation) |
| Latin-Extended | Gdańsk | the WinAnsi letters render; ń shows `?` |

## Scripts the bundled font does not cover

The bundled DejaVuSans has no CJK glyphs. Each CJK codepoint renders a visible `[U+XXXX]` marker instead, and inkmd raises one `MissingGlyphWarning` naming the missing codepoints. Full CJK rendering is a planned later font pack.

- Japanese: 日本語
- Chinese: 你好世界
- Korean: 안녕하세요

## Mixed scripts in one line

inkmd splits a run per codepoint, so a single line can switch scripts and route each part to the right path: English stays on the base-14 font, Cyrillic and Greek go to the embedded font, and CJK falls to a marker.

The badge read "Welcome, Добро пожаловать, Καλώς ορίσατε, 欢迎" in four scripts at once.
