#!/usr/bin/env python3
"""Build a LibreOffice ODT of the Book of Mormon in Middle English."""

import os
import re

import pyphen
from odf.opendocument import OpenDocumentText
from odf.style import (
    Columns,
    DropCap,
    FontFace,
    MasterPage,
    PageLayout,
    PageLayoutProperties,
    ParagraphProperties,
    Style,
    TextProperties,
)
from odf.text import P

SRC_DIR = "/Users/stay/mike/architecture/dictionary/out/bom_middle_english"
OUT_PATH = os.path.join(SRC_DIR, "book_of_mormon.odt")
FONT = "ALOT Gutenberg A"
DROPCAP_FONT = "Lombardic"

INDEX_LINE_RE = re.compile(r"^(\S+\.txt)\s+(.+?)\s+\(\d+ verses\)\s*$")
VERSE_RE = re.compile(r"^¶\s*\d+:\d+\s+(.*)$")


def read_index():
    entries = []
    with open(os.path.join(SRC_DIR, "INDEX.txt"), encoding="utf-8") as f:
        for line in f:
            m = INDEX_LINE_RE.match(line.strip())
            if not m:
                continue
            entries.append((m.group(1), m.group(2)))
    return entries


CHAR_TABLE = str.maketrans({
    "ȝ": "3", "Ȝ": "3",
    "⁊": "&",
    # ALOT Gutenberg A keys its long-s glyph off '#' (numbersign): a bare '#'
    # renders as ſ, and '#t', '#i', '#d', '#f', '##', '#z' trigger the ligatures
    # longs_t, ls_i, ls_d, ls_f, ls_ls, and ß respectively.
    "ſ": "#",
})

# --- Hyphenation ---------------------------------------------------------
# Pyphen (Hunspell en_US) covers common English roots. For the Middle
# English forms it doesn't recognize (britheren, jeruſalem, ſchulden, ...)
# we fall back to a simple sonority-based V-CV / VC-CV syllabifier.

_PYPHEN = pyphen.Pyphen(lang="en_US")

SHY = "­"  # soft hyphen
WORD_RE = re.compile(r"[A-Za-zſȝȜ]+")
VOWELS = set("aeiouyAEIOUY")
DIGRAPHS = {"th", "ch", "sh", "gh", "wh", "ph"}
MIN_LEN = 6                # never hyphenate shorter words
MIN_BEFORE = 2             # >=2 chars before break (matches ODT style)
MIN_AFTER = 3              # >=3 chars after break (matches ODT style)
RULE_FALLBACK_MIN_LEN = 8  # rule-based only when pyphen misses and word long


def _norm_letter(c):
    if c == "ſ":
        return "s"
    if c == "ȝ":
        return "g"
    if c == "Ȝ":
        return "G"
    return c


def _cclass(c):
    n = _norm_letter(c)
    if n in VOWELS:
        return "V"
    if n.isalpha():
        return "C"
    return "X"


def _rule_hyphens(word):
    """Return positions where a soft hyphen can go, by V-CV / VC-CV rule."""
    n = len(word)
    if n < MIN_LEN:
        return []
    types = [_cclass(c) for c in word]
    positions = []
    i = 1
    while i < n:
        if types[i - 1] == "V" and types[i] == "C":
            j = i
            while j < n and types[j] == "C":
                j += 1
            if j < n and types[j] == "V":
                cluster_len = j - i
                if cluster_len == 1:
                    split_pos = i          # V-CV
                else:
                    first_two = (_norm_letter(word[i]) + _norm_letter(word[i + 1])).lower()
                    if first_two in DIGRAPHS:
                        # Keep digraph intact; break before it (or after, if longer cluster).
                        split_pos = i if cluster_len == 2 else i + 2
                    else:
                        split_pos = i + 1  # VC-CV
                if MIN_BEFORE <= split_pos <= n - MIN_AFTER:
                    positions.append(split_pos)
                i = j
                continue
        i += 1
    return positions


def hyphenate_word(word):
    if len(word) < MIN_LEN:
        return word
    # Union of pyphen and rule-based positions: pyphen gets dictionary-correct
    # splits for recognized English roots; the rule fills in the ME-specific
    # gaps and adds extra breakpoints pyphen would miss (e.g. pro-phe-cie-den
    # where pyphen only offers prophe-cieden).
    lookup = "".join(_norm_letter(c) for c in word)
    inserted = _PYPHEN.inserted(lookup, hyphen="\x01")
    positions = set()
    orig_i = 0
    for ch in inserted:
        if ch == "\x01":
            if MIN_BEFORE <= orig_i <= len(word) - MIN_AFTER:
                positions.add(orig_i)
        else:
            orig_i += 1
    if len(word) >= RULE_FALLBACK_MIN_LEN:
        positions.update(_rule_hyphens(word))
    if not positions:
        return word
    # Drop positions that would leave a fragment < 2 chars between hyphens
    # (e.g. avoid myſ-te-r-ies produced by union of pyphen [3,6] + rule [5]).
    filtered = []
    last = -2
    for p in sorted(positions):
        if p - last >= 2:
            filtered.append(p)
            last = p
    result = word
    for p in reversed(filtered):
        result = result[:p] + SHY + result[p:]
    return result


def hyphenate_text(text):
    return WORD_RE.sub(lambda m: hyphenate_word(m.group(0)), text)


def read_chapter_text(path):
    """Return the chapter's body as one continuous string, no verse markers."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    pieces = []
    for line in lines[2:]:  # skip title + blank line
        s = line.strip()
        if not s:
            continue
        m = VERSE_RE.match(s)
        pieces.append(m.group(1) if m else s)
    joined = " ".join(pieces)
    # Hyphenate while ȝ/ſ are still letters, then map to display glyphs.
    return hyphenate_text(joined).translate(CHAR_TABLE)


def read_preamble_text(path):
    """Return an unnumbered preamble (title page, book intro, or chapter
    superscription) as one continuous string, or None if the file is absent.

    Files are plain UTF-8 with no title header and no verse markers — every
    non-empty line contributes to a single joined paragraph."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        pieces = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
    if not pieces:
        return None
    joined = " ".join(pieces)
    return hyphenate_text(joined).translate(CHAR_TABLE)


def book_of(title):
    return title.rsplit(" ", 1)[0]


def build():
    doc = OpenDocumentText()

    doc.fontfacedecls.addElement(
        FontFace(name=FONT, fontfamily=f'"{FONT}"')
    )
    doc.fontfacedecls.addElement(
        FontFace(name=DROPCAP_FONT, fontfamily=f'"{DROPCAP_FONT}"')
    )

    page_layout = PageLayout(name="MainLayout", pageusage="mirrored")
    plp = PageLayoutProperties(
        pagewidth="11in",
        pageheight="17in",
        printorientation="portrait",
        marginleft="1.75in",   # inner
        marginright="2in",     # outer
        margintop="1.5in",
        marginbottom="3in",
    )
    plp.addElement(Columns(columncount="2", columngap="0.75in"))
    page_layout.addElement(plp)
    doc.automaticstyles.addElement(page_layout)

    doc.masterstyles.addElement(
        MasterPage(name="Standard", pagelayoutname="MainLayout")
    )

    # Column height 12.5" (900pt) / 42 lines = 21.4286pt per line; round down.
    line_height = "21.4pt"
    body_font_size = "20pt"

    standard = Style(name="Standard", family="paragraph")
    standard.addElement(
        TextProperties(
            fontname=FONT,
            fontsize=body_font_size,
            language="en",
            country="US",
            hyphenate="true",
            hyphenationremaincharcount="2",
            hyphenationpushcharcount="3",
        )
    )
    standard.addElement(
        ParagraphProperties(
            textalign="justify",
            marginbottom="0in",
            margintop="0in",
            lineheight=line_height,
            hyphenationladdercount="no-limit",
        )
    )
    doc.styles.addElement(standard)

    body = Style(name="Body", family="paragraph", parentstylename="Standard")
    body.addElement(
        ParagraphProperties(
            textalign="justify",
            textindent="0.25in",
            marginbottom="0in",
            margintop="0in",
            lineheight=line_height,
        )
    )
    doc.styles.addElement(body)

    # Text style applied to the drop-cap glyph itself: Lombardic (a display
    # capitals face that sizes cleanly to the enclosing line count) rendered
    # in white so the printed cap is invisible and only the reserved box
    # remains — ready for a hand-drawn rubricated cap.
    dropcap_char = Style(name="DropCapChar", family="text")
    dropcap_char.addElement(
        TextProperties(fontname=DROPCAP_FONT, color="#ffffff")
    )
    doc.styles.addElement(dropcap_char)

    def make_dropcap_style(name, lines):
        s = Style(name=name, family="paragraph", parentstylename="Body")
        pp = ParagraphProperties(
            textalign="justify",
            textindent="0in",
            marginbottom="0in",
            margintop="0in",
            lineheight=line_height,
        )
        pp.addElement(
            DropCap(
                lines=str(lines),
                length="1",
                distance="0.08in",
                stylename="DropCapChar",
            )
        )
        s.addElement(pp)
        doc.styles.addElement(s)

    make_dropcap_style("BookOpener", 6)
    make_dropcap_style("ChapterOpener", 3)

    # Between-books colophon: red, centered, no dropcap.
    colophon_style = Style(name="Colophon", family="paragraph")
    colophon_style.addElement(
        ParagraphProperties(
            textalign="center",
            margintop="0in",
            marginbottom="0in",
            lineheight=line_height,
        )
    )
    colophon_style.addElement(
        TextProperties(
            fontname=FONT,
            fontsize=body_font_size,
            color="#b22222",
        )
    )
    doc.styles.addElement(colophon_style)

    def finalize(text):
        # Y (pronoun-I) → y except at the dropcap and its following letter;
        # also uppercase the letter immediately after the dropcap.
        head, tail = text[:2], text[2:].replace("Y", "y")
        if len(head) >= 2 and head[1].islower():
            head = head[0] + head[1].upper()
        return head + tail

    def emit(text, style_name):
        if not text:
            return
        doc.text.addElement(P(stylename=style_name, text=finalize(text)))

    # Title page — its own leading paragraph, 6-line dropcap.
    title_page = read_preamble_text(os.path.join(SRC_DIR, "title_page.txt"))
    if title_page:
        emit(title_page, "BookOpener")

    # ME forms of the book names used in the between-books colophons.
    BOOK_ME = {
        "1 Nephi":         "firſte book of Nephi",
        "2 Nephi":         "ſecounde book of Nephi",
        "Jacob":           "book of Jacob",
        "Enos":            "book of Enos",
        "Jarom":           "book of Jarom",
        "Omni":            "book of Omni",
        "Words of Mormon": "wordis of Mormon",
        "Mosiah":          "book of Moſie",
        "Alma":            "book of Alma",
        "Helaman":         "book of Helaman",
        "3 Nephi":         "thridde book of Nephi",
        "4 Nephi":         "fourthe book of Nephi",
        "Mormon":          "book of Mormon",
        "Ether":           "book of Ether",
        "Moroni":          "book of Moroni",
    }

    def emit_colophon(prev_book, next_book):
        text = (f"Here endith the {BOOK_ME[prev_book]}. "
                f"Here bigynneth the {BOOK_ME[next_book]}.")
        text = hyphenate_text(text).translate(CHAR_TABLE)
        doc.text.addElement(P(stylename="Colophon", text=text))

    entries = read_index()
    current_book = None

    for fname, title in entries:
        book = book_of(title)
        first_of_book = book != current_book
        if first_of_book and current_book is not None:
            emit_colophon(current_book, book)
        current_book = book

        # Book intros are their own paragraph with a 3-line dropcap so the
        # book's first verse still gets the prominent 6-line dropcap.
        if first_of_book:
            book_prefix = re.sub(r"_\d+\.txt$", "", fname)
            intro = read_preamble_text(
                os.path.join(SRC_DIR, f"{book_prefix}_intro.txt")
            )
            if intro:
                emit(intro, "ChapterOpener")

        # Chapter superscriptions are absorbed into the chapter paragraph
        # (they already share the 3-line dropcap size, so merging is fine).
        pieces = []
        superscription = read_preamble_text(
            os.path.join(SRC_DIR, fname[:-4] + "_super.txt")
        )
        if superscription:
            pieces.append(superscription)

        chapter = read_chapter_text(os.path.join(SRC_DIR, fname))
        if chapter:
            pieces.append(chapter)

        combined = " ".join(pieces)
        style_name = "BookOpener" if first_of_book else "ChapterOpener"
        emit(combined, style_name)

    doc.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
