#!/usr/bin/env python3
"""Build a LibreOffice ODT of the Book of Mormon in Middle English.

Runs a two-pass build so each chapter's Roman-numeral marginalia lands in
whichever page margin is nearest its anchor:

  1. Build a probe ODT with frames tentatively placed on the left, convert
     to PDF, and inspect the layout to see which column each chapter's body
     text actually starts in.
  2. Rebuild the ODT with per-chapter frame positioning: left column ->
     left margin (inner on recto, outer on verso); right column -> right
     margin (outer on recto, inner on verso). Frames are transparent with
     wrap=run-through, so the body flow of pass 1 and pass 2 is identical
     and the pass-1 column reading remains valid for pass 2.
"""

import json
import os
import re
import subprocess

import pyphen
from odf.config import ConfigItem, ConfigItemSet
from odf.draw import Frame, TextBox
from odf.opendocument import OpenDocumentText
from odf.style import (
    Columns,
    DropCap,
    FontFace,
    GraphicProperties,
    MasterPage,
    PageLayout,
    PageLayoutProperties,
    ParagraphProperties,
    Style,
    TextProperties,
)
from odf.text import P, Span

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


LIGATURE_PAIRS = {"ff", "fi", "fl", "ft", "ct", "ch", "ck", "tt", "tz"}


def _is_forbidden_split(word, pos):
    """SHY at position `pos` would land between word[pos-1] and word[pos].
    Don't split there if the pair forms one of the font's ligatures — LO
    otherwise fires the ligature *across* the SHY and then also on the
    trailing portion, drawing the ligature twice."""
    if pos <= 0 or pos >= len(word):
        return False
    pair = (word[pos - 1] + word[pos]).lower().replace("ſ", "s")
    return pair in LIGATURE_PAIRS


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
        if p - last >= 2 and not _is_forbidden_split(word, p):
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


def chapter_of(title):
    return int(title.rsplit(" ", 1)[1])


_ROMAN = [
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
    (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
    (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
]


def to_roman(n):
    r = ""
    for val, sym in _ROMAN:
        while n >= val:
            r += sym
            n -= val
    return r


def _chapter_key(fname):
    return fname[:-4]  # strip .txt


def chapter_opening_probe(fname):
    """First ~20 chars of the chapter paragraph's text as it will appear
    in the rendered PDF (superscription prepended if any; SHY stripped;
    Y→y transform applied to everything past position 2). Used to locate
    the paragraph's start column during the probe pass."""
    parts = []
    super_path = os.path.join(SRC_DIR, fname[:-4] + "_super.txt")
    if os.path.exists(super_path):
        s = read_preamble_text(super_path)
        if s:
            parts.append(s)
    chap = read_chapter_text(os.path.join(SRC_DIR, fname))
    if chap:
        parts.append(chap)
    text = " ".join(parts)
    # Apply Y→y everywhere except positions 0 and 1 (dropcap and next letter)
    head, tail = text[:2], text[2:].replace("Y", "y")
    if len(head) >= 2 and head[1].islower():
        head = head[0] + head[1].upper()
    text = head + tail
    # Strip soft hyphens for matching against extracted PDF text; skip the
    # first character because the dropcap letter is drawn in white Lombardic
    # and pypdf doesn't include it in extract_text output.
    text = text.replace(SHY, "")
    return text[1:30]


def build(out_path=OUT_PATH, chapter_placements=None):
    """Build an ODT.

    chapter_placements: optional dict
        {chapter_key -> {"column": "left"|"right", "parity": "odd"|"even"}}
    describing where each chapter's body actually starts (as observed from a
    probe render). None (or missing entries) → the frame goes to a fixed
    left position that doesn't affect body flow (used in the probe pass)."""
    chapter_placements = chapter_placements or {}
    doc = OpenDocumentText()

    # Force "printer-independent" layout so desktop LibreOffice and headless
    # soffice --convert-to pdf agree on line breaks and pagination. Without
    # this, screen metrics and printer metrics differ subtly, causing a
    # chapter to land in different columns/pages between probe and viewer
    # (which then puts marginal chapter numerals on the wrong side in the
    # desktop view).
    cs = ConfigItemSet(name="ooo:configuration-settings")
    cs.addElement(
        ConfigItem(
            name="PrinterIndependentLayout",
            type="string",
            text="high-resolution",
        )
    )
    doc.settings.addElement(cs)

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

    make_dropcap_style("BookOpener", 5)
    make_dropcap_style("ChapterOpener", 3)

    # Chapter number: a small text frame anchored to the paragraph, positioned
    # "outside" (i.e., the outer margin of whichever page the chapter starts
    # on — the outer margin flips across recto/verso for mirrored layouts, so
    # this always lands in a page margin and never in the between-columns
    # gutter, satisfying the "inner or outer, never between the columns" rule).
    # draw:textarea-horizontal-align is what LibreOffice actually respects
    # for text inside a draw:text-box — the paragraph's own fo:text-align is
    # ignored in that context. Two frame styles differ only in that attr:
    # left-margin frames align text to the right (hugging the column),
    # right-margin frames align to the left.
    def make_chnum_frame_style(name, tha):
        s = Style(name=name, family="graphic")
        s.addElement(
            GraphicProperties(
                verticalpos="from-top",
                verticalrel="paragraph",
                horizontalpos="from-left",
                horizontalrel="page",
                wrap="run-through",
                runthrough="foreground",
                fill="none",
                stroke="none",
                textareahorizontalalign=tha,
            )
        )
        doc.automaticstyles.addElement(s)
        return s

    chnum_frame_left = make_chnum_frame_style("ChapNumFrameLeft", "right")
    chnum_frame_right = make_chnum_frame_style("ChapNumFrameRight", "left")

    chnum_para_style = Style(name="ChapNumPara", family="paragraph")
    chnum_para_style.addElement(
        ParagraphProperties(lineheight="100%")
    )
    doc.styles.addElement(chnum_para_style)

    # Text-family span style that draws an overline. Used to render the
    # scribal abbreviation "iblþ" — ALOT Gutenberg A has no glyphs for the
    # precomposed macron-b or the special thorn-with-stroke (U+A765), so we
    # add the horizontal strokes with markup on plain letters instead.
    overline_span_style = Style(name="OverlineSpan", family="text")
    overline_span_style.addElement(
        TextProperties(
            textoverlinestyle="solid",
            textoverlinewidth="auto",
            textoverlinecolor="font-color",
        )
    )
    doc.styles.addElement(overline_span_style)

    def add_body_text(p, text):
        """Add body text to a paragraph, expanding the manuscript abbreviation
        "ib̄lꝥ" (i + b-with-macron + l + thorn-with-stroke) into
        i + <overline>b</overline> + l + <overline>þ</overline> — the ALOT
        Gutenberg A font has no glyphs for U+0304 (combining macron) or
        U+A765 (Latin thorn-with-stroke), so we draw the horizontal strokes
        with markup on plain letters that the font renders natively."""
        parts = text.split("ib̄lꝥ")
        for i, chunk in enumerate(parts):
            if chunk:
                p.addText(chunk)
            if i < len(parts) - 1:
                p.addText("i")
                p.addElement(Span(stylename=overline_span_style, text="b"))
                p.addText("l")
                p.addElement(Span(stylename=overline_span_style, text="þ"))

    # Text-family style for the numeral glyphs themselves. Paragraph-level
    # text-properties inside a draw:text-box aren't consistently applied by
    # LibreOffice (color/font were being ignored), so we wrap the numeral in
    # a text:span carrying the font/size/color explicitly.
    #
    # NOTE: this MUST live in automatic-styles (not styles) — LibreOffice
    # ignores office:styles text properties on spans inside a draw:text-box.
    chnum_span_style = Style(name="ChapNumSpan", family="text")
    chnum_span_style.addElement(
        TextProperties(fontname=FONT, fontsize="20pt", color="#b22222")
    )
    doc.automaticstyles.addElement(chnum_span_style)

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
            hyphenate="false",
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

    # Frame x-offset (from page's left edge) so the frame sits ~0.25" from
    # the column boundary, regardless of which side / which page-orientation
    # the chapter is on. Frame width is 0.9"; margins are inner=1.75"/outer=2".
    #   recto/left  -> LEFT column,  INNER margin (0.00–1.75"): x = 0.60"
    #   recto/right -> RIGHT column, OUTER margin (9.00–11.0"): x = 9.25"
    #   verso/left  -> LEFT column,  OUTER margin (0.00–2.00"): x = 0.85"
    #   verso/right -> RIGHT column, INNER margin (9.25–11.0"): x = 9.50"
    FRAME_X = {
        ("odd",  "left"):  "0.60in",
        ("odd",  "right"): "9.25in",
        ("even", "left"):  "0.85in",
        ("even", "right"): "9.50in",
    }

    def emit(text, style_name, roman=None, placement=None):
        """Emit a paragraph. If roman is given, prepend a chapter-number
        frame anchored to the paragraph, positioned in the page margin on
        the side matching `placement` ({'column':..., 'parity':...}). If
        placement is None (probe pass) the frame defaults to a fixed left
        position that doesn't affect body flow."""
        if not text:
            return
        p = P(stylename=style_name)
        if roman:
            col = placement["column"] if placement else "left"
            if placement:
                x = FRAME_X[(placement["parity"], col)]
            else:
                x = "0.50in"
            style = chnum_frame_right if col == "right" else chnum_frame_left
            frame = Frame(
                anchortype="paragraph",
                width="0.9in",
                height="0.35in",
                x=x,
                y="0in",
                stylename=style,
            )
            box = TextBox()
            para = P(stylename=chnum_para_style)
            para.addElement(Span(stylename=chnum_span_style, text=roman))
            box.addElement(para)
            frame.addElement(box)
            p.addElement(frame)
        add_body_text(p, finalize(text))
        doc.text.addElement(p)

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

    def emit_colophon_text(text):
        # Rubrics don't get hyphenated: no SHYs inserted, and the Colophon
        # style has hyphenate="false" so LO's runtime hyphenator stays off.
        doc.text.addElement(
            P(stylename="Colophon", text=text.translate(CHAR_TABLE))
        )

    def emit_colophon(prev_book, next_book):
        emit_colophon_text(
            f"Here endith the {BOOK_ME[prev_book]}. "
            f"Here bigynneth the {BOOK_ME[next_book]}."
        )

    # Opening incipit for the whole corpus, sitting between the title page
    # and the 1 Nephi introduction.
    emit_colophon_text("Here bigynneth the book of Nephi.")

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
        emit(
            combined,
            style_name,
            roman=to_roman(chapter_of(title)),
            placement=chapter_placements.get(_chapter_key(fname)),
        )

    # Closing explicit after the last chapter of Moroni.
    emit_colophon_text("Here endith the book of Moroni.")

    doc.save(out_path)
    print(f"Wrote {out_path}")


# ---------------------------------------------------------------------------
# Two-pass build: probe render -> analyze -> final render
# ---------------------------------------------------------------------------

SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
# Column boundary: the between-columns gutter falls around x = 5.375 in
# from the page's left edge. Anything left of that starts in the left
# column, anything right of it starts in the right column. Using 5 in
# (360 pt) gives a comfortable margin against noise.
COLUMN_SPLIT_PT = 360


def convert_to_pdf(odt_path, out_dir):
    subprocess.run(
        [SOFFICE, "--headless", "--convert-to", "pdf",
         "--outdir", out_dir, odt_path],
        check=True,
    )
    return os.path.join(
        out_dir,
        os.path.splitext(os.path.basename(odt_path))[0] + ".pdf",
    )


def _strip_noise(s):
    """Normalize text for cross-matching probe strings against pypdf
    output: drop whitespace and dashes (PDF line-break hyphens)."""
    return re.sub(r"[\s\-­]+", "", s)


def probe_chapter_columns(pdf_path):
    """Return {chapter_key -> {'column':'left'|'right', 'parity':'odd'|'even'}}
    by finding each chapter's opening text in the rendered PDF, in
    document order — a cursor advances past each match so that chapters
    with identical opening formulas (e.g. Mosiah 4 & 5 both begin "And
    now, whanne kyng Beniamyn hadde …") don't collide onto the earlier
    chapter's location. `parity` follows PDF page numbering
    (1 = odd = recto)."""
    from pypdf import PdfReader
    entries = read_index()
    openings = [
        (_chapter_key(fn), _strip_noise(chapter_opening_probe(fn))[:30])
        for fn, _ in entries
    ]
    reader = PdfReader(pdf_path)
    # Extract every non-whitespace character in reading order, tracking
    # the page + x-coord where each landed.
    chars, char_pg, char_x = [], [], []
    for pgnum, page in enumerate(reader.pages, start=1):
        runs = []
        def visit(text, cm, tm, font_dict, font_size):
            if text:
                runs.append((tm[4], text))
        page.extract_text(visitor_text=visit)
        for x, txt in runs:
            for ch in txt:
                if re.match(r"[\s\-­]", ch):
                    continue
                chars.append(ch)
                char_pg.append(pgnum)
                char_x.append(x)
    doc_text = "".join(chars)
    result = {}
    cursor = 0
    for key, probe in openings:
        if not probe:
            continue
        idx = doc_text.find(probe, cursor)
        if idx < 0:
            continue
        result[key] = {
            "column": "left" if char_x[idx] < COLUMN_SPLIT_PT else "right",
            "parity": "odd" if char_pg[idx] % 2 else "even",
        }
        cursor = idx + len(probe)
    return result


def main():
    tmp_dir = os.path.join(SRC_DIR, ".probe")
    os.makedirs(tmp_dir, exist_ok=True)
    probe_odt = os.path.join(tmp_dir, "probe.odt")

    print("Pass 1: probe render...")
    build(out_path=probe_odt, chapter_placements=None)
    probe_pdf = convert_to_pdf(probe_odt, tmp_dir)

    print("Analyzing probe PDF for chapter placements...")
    placements = probe_chapter_columns(probe_pdf)
    left = sum(1 for v in placements.values() if v["column"] == "left")
    right = sum(1 for v in placements.values() if v["column"] == "right")
    print(f"  placements detected: {len(placements)} chapters "
          f"(left={left}, right={right})")
    with open(os.path.join(tmp_dir, "columns.json"), "w") as f:
        json.dump(placements, f, indent=2, sort_keys=True)

    print("Pass 2: final render...")
    build(out_path=OUT_PATH, chapter_placements=placements)


if __name__ == "__main__":
    main()
