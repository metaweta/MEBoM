# MEBoM — the Book of Mormon in Middle English

A Wycliffe-inflected Middle English translation of the Book of Mormon, plus a
Python script that typesets it as a two-column tabloid ODT with authentic
period features: long-s, yogh, Tyronian et, blackletter ligatures, and blank
Lombardic drop caps ready for hand rubrication.

## Contents

- **`*.txt`** — 239 numbered chapter files (`1_nephi_001.txt` … `moroni_010.txt`),
  each verse prefixed with `¶ C:V`.
- **`INDEX.txt`** — canonical chapter order.
- **`title_page.txt`, `{book}_intro.txt`, `{chapter}_super.txt`** — the 23
  unnumbered "extracapitular" blocks (title page, seven book introductions,
  fifteen chapter superscriptions) that the modern edition treats as
  translated plate text.
- **`build_bom_odt.py`** — generates `book_of_mormon.odt` from the sources.
- **`book_of_mormon.odt`** — the generated document (checked in for
  convenience; regenerate any time with the script).

## Typography

- Page: 11″ × 17″, mirrored margins (inner 1.75″ / outer 2″ / top 1.5″ /
  bottom 3″), two 3.25″ columns with 0.75″ gutter, 12.5″ column height,
  42 lines per column at 20 pt.
- Body font: [ALOT Gutenberg A](https://www.alterlittera.com/) (Alter Littera).
- Drop caps: 6-line for book openers, 3-line for chapter openers, rendered
  in white [Lombardic](https://en.wikipedia.org/wiki/Lombardic_capitals) —
  reserved space for hand-drawn rubricated caps.
- Character substitutions the script performs at render time:
  - `ȝ` (yogh) → `3` (matches the numeral shape in the font)
  - `⁊` (Tyronian et) → `&` (the font draws `&` as a Tyronian et)
  - `ſ` (long-s) → `#` (the font keys its long-s ligatures — `#t`, `#i`,
    `#f`, `#d`, `##`, `#z` — off the numbersign codepoint)
- Ligatures firing automatically via OpenType `liga`: `ff, fi, fl, ffi, ffl,
  ft, ct, ch, ck, tt, tz, æ, œ`, plus the long-s pairs above.
- Soft hyphens inserted at syllable boundaries using pyphen (`en_US`) with a
  V-CV / VC-CV rule-based fallback for Middle English words the dictionary
  doesn't recognize; LibreOffice runtime hyphenation is also enabled.
- Capital `Y` (used in the corpus for the pronoun "I") is lowercased in
  body text, except at the dropcap position and the letter immediately
  after it.

## Build

```sh
python3 -m venv .venv
.venv/bin/pip install odfpy pyphen
.venv/bin/python build_bom_odt.py
```

Producing a PDF:

```sh
/Applications/LibreOffice.app/Contents/MacOS/soffice --headless \
    --convert-to pdf book_of_mormon.odt
```

## Fonts

The output relies on two OpenType fonts that must be installed locally:

- **ALOT Gutenberg A** (Alter Littera) — the blackletter body font. Without
  it, LibreOffice will substitute and the long-s ligatures will not fire.
- **Lombardic** — used for the (invisible white) drop cap letter so the
  reserved box has authentic Lombardic proportions.

## License

The source text and translations in this repository are the author's work
and released under CC BY 4.0. The script is MIT.
