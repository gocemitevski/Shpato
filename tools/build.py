#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a normalized catalog from the MRTV phonotheque CSVs.

Reads the four source CSV files (left untouched), normalizes records,
and writes:
  data/catalog.json    - normalized records + meta
  data/catalog.js      - same, as a global for file:// usage
  data/notes.json      - every fix / flag applied, for transparency
  data/notes.js        - same, as a global
  dela.html            - the same works as one plain document, for crawlers
                         that do not run scripts

It also merges sources/youtube.csv, the record -> YouTube video map (columns
`id,title,video,found,lengthSec,added`; see the README), into each record's
"video" field, and records the links that were found by search rather than
checked by hand as an approximate match.

Only the Python 3 standard library is used.
"""

import csv
import datetime
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SOURCES_DIR = os.path.join(ROOT, "sources")

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------
# schema columns, in order, for each category. The "temi" file ships a wrong
# header (it omits the author column even though its rows contain it), so the
# schema is defined here rather than trusted from the file.
SOURCES = [
    {
        "category": "vocal",
        "file": "Vokalni_kompozicii_od_Dragan_Gjakonovski_Shpato.csv",
        "columns": ["title", "performer", "minutes", "signature"],
    },
    {
        "category": "instrumental",
        "file": "Instrumentalni_kompozicii_od_Dragan_Gjakonovski_Shpato.csv",
        "columns": ["title", "performer", "minutes", "signature"],
    },
    {
        "category": "arrThemes",
        "file": "Aranzhmani_na_Dragan_Gjakonovski_Shpato_na_temi_od_drugi_avtori.csv",
        "columns": ["title", "composer", "performer", "minutes", "signature"],
    },
    {
        "category": "arrVocal",
        "file": "Aranzhmani_na_Dragan_Gjakonovski_Shpato_na_vokalni_tvorbi_od_drugi_avtori.csv",
        "columns": ["title", "composer", "performer", "minutes", "signature"],
    },
]

# A signature is an optional latin/cyrillic letter code, an optional dash,
# then the rest (number, optionally /sub).
SIG_RE = re.compile(r"^([A-Za-z\u0400-\u04FF]{1,3})-?(.*)$")
DIGITS_RE = re.compile(r"\D")
# Latin letters that stand in for Cyrillic ones in some raw signatures.
LATIN_PREFIX = {
    "Z": "З", "A": "А", "B": "Б", "C": "Ц", "E": "Е", "H": "Н", "K": "К",
    "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
}

SEVERITY = {
    "performer-placeholder": "info",
    "performer-author": "info",
    "ensemble-expanded": "info",
    "performer-split": "info",
    "punctuation-spacing": "info",
    "ellipsis-normalized": "info",
    "mixed-script": "warning",
    "abbreviation-normalized": "info",
    "typo-corrected": "warning",
    "name-unified": "info",
    "duration-missing-separator": "warning",
    "duration-ambiguous-seconds": "warning",
    "duration-unparseable": "warning",
    "signature-missing-prefix": "info",
    "signature-double-prefix": "warning",
    "signature-trailing-slash": "info",
    "signature-missing-dash": "info",
    "signature-latin-prefix": "info",
    "signature-suspicious": "warning",
    "composer-placeholder": "info",
    "video-approximate": "info",
    "duplicate": "info",
    "duplicate-dropped": "info",
    "possible-duplicate": "warning",
    "missing-signature": "info",
    "missing-duration": "info",
    "missing-performer": "info",
}


def clean(value):
    return re.sub(r"\s+", " ", (value or "").replace("\ufeff", "")).strip()


# ---------------------------------------------------------------------------
# Field normalizers
# ---------------------------------------------------------------------------
def parse_duration(raw, flags):
    """Return (seconds|None, raw). Annotates flags."""
    s = raw.strip()
    if not s:
        flags.append("missing-duration")
        return None, raw
    if s.isdigit():
        if len(s) == 3:
            # e.g. 405 -> 4:05
            flags.append("duration-missing-separator")
            return int(s[0]) * 60 + int(s[1:]), raw
        flags.append("duration-unparseable")
        return None, raw
    if "." in s:
        minutes, _, seconds = s.partition(".")
        try:
            mm = int(minutes)
        except ValueError:
            flags.append("duration-unparseable")
            return None, raw
        seconds = seconds.strip()
        if seconds == "":
            ss = 0
        elif len(seconds) == 1:
            # e.g. 3.7 -> 3:07 (ambiguous)
            flags.append("duration-ambiguous-seconds")
            ss = int(seconds)
        else:
            try:
                ss = int(seconds)
            except ValueError:
                flags.append("duration-unparseable")
                return None, raw
        if ss >= 60:
            flags.append("duration-unparseable")
            return None, raw
        return mm * 60 + ss, raw
    flags.append("duration-unparseable")
    return None, raw


def normalize_signature(raw, flags):
    """Return (canonical|None, collection|None, raw)."""
    s = clean(raw)
    if not s:
        flags.append("missing-signature")
        return None, None, raw
    if s.endswith("/"):
        flags.append("signature-trailing-slash")
        s = s.rstrip("/")

    m = SIG_RE.match(s)
    if m and m.group(1):
        prefix, rest = m.group(1), m.group(2)
        if prefix.isascii() and prefix.isalpha():
            prefix = "".join(LATIN_PREFIX.get(ch.upper(), ch) for ch in prefix)
            flags.append("signature-latin-prefix")
        # missing dash: prefix immediately followed by a digit
        if not re.match(r"^[A-Za-z\u0400-\u04FF]{1,3}-", s):
            flags.append("signature-missing-dash")
    else:
        prefix, rest = "З", s
        flags.append("signature-missing-prefix")

    # doubled prefix, e.g. З-З-7683/2
    if rest.startswith(prefix + "-"):
        flags.append("signature-double-prefix")
        rest = rest[len(prefix) + 1:]

    canonical = "{}-{}".format(prefix, rest)
    # A signature that is just a long number with no "/sub" part is suspicious
    # (e.g. З-30061 vs the expected З-3006/1).
    if "/" not in rest and len(DIGITS_RE.sub("", rest)) >= 5:
        flags.append("signature-suspicious")
    return canonical, prefix, raw


# ---------------------------------------------------------------------------
# Text cleanup (spacing, script mixing, typos, name unification)
# ---------------------------------------------------------------------------
# Latin letters that are visually identical to Cyrillic ones. They only get
# rewritten inside a word that also contains Cyrillic letters, so genuinely
# Latin names (Gershwin, Vivaldi, ...) are left alone.
LATIN_TO_CYRILLIC = {
    "a": "а", "c": "с", "e": "е", "k": "к", "m": "м", "o": "о", "p": "р",
    "t": "т", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
}
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
LATIN_RE = re.compile(r"[A-Za-z]")
# "Т.О." is an in-house ensemble abbreviation; the file spells it both with
# and without dots, so it is canonicalised to the plain form. The rest are the
# shorthand the export writes inside a role: the same word twice with two
# spellings ("ар." and "арр."), an instrument clipped to four letters ("сакс"),
# and a year with its "г" run into it ("сним. 1959г"). Each is a word, not a
# prefix, so "саксофон" is never touched twice.
ABBREVIATIONS = [
    (re.compile(r"\bТ\.\s*О\.?(?=\s|$)"), "ТО"),
    (re.compile(r"\bарр\."), "ар."),
    (re.compile(r"\bсакс\b"), "саксофон"),
    (re.compile(r"(?<=\d)г\b"), ""),
]
# Clear misspellings, keyed by the value *after* the generic cleanups.
TYPO_MAP = {
    "Имулси": "Импулси",
    "Андреа Сопронив": "Андреа Сопронов",
    "С. Грчаровски": "С. Грнчаровски",
}
# The same person or ensemble credited in more than one way. Keyed by the
# value *after* the generic cleanups and, for performers, after the name/role
# split. Every pair is unambiguous (matching surname, or a single-name match).
NAME_ALIASES = {
    # composers
    "Г. Копров": "Григор Копров",
    "А. Џамбазов": "Александар Џамбазов",
    "Џамбазов": "Александар Џамбазов",
    "К. Милев": "Кирил Милев",
    "К. Портер": "Кол Портер",
    "Х. Крствески": "Христо Крстевски",
    "Х Крстевски": "Христо Крстевски",
    "Паркс": "C. Parks",
    "Ливингстон": "Livingston / Evans",
    "Џ. Гершвин": "G. Gershwin",
    "Ѓ. Елигтон": "Дјук Елингтон",
    "Гилар": "М. Гилар",
    # performers
    "В. Томновска": "Виолета Томовска",
    "С. Петкповска": "Сашка Петковска",
    "З. Јовановиќ": "Зоран Јовановиќ",
    "Љ. Босилков": "Љупчо Босилков",
    "Љ. Димитровска": "Љупка Димитровска",
    "Б. Ноев": "Божидар Ноев",
    "А. Сопронов": "Андреа Сопронов",
    "К. Рибарски": "Кирил Рибарски",
    "Македонија": "група Македонија",
    "Н. Кимов": "Никола Комовски",
    "Н. Кимовски": "Никола Комовски",
    "Н. Комовски": "Никола Комовски",
    # ensembles written in an abbreviated form
    "Забавен анс. На РС": "Забавен оркестар на РС",
    "Забавен анс. на РС": "Забавен оркестар на РС",
    "Забавен орк. на РС": "Забавен оркестар на РС",
}
TEXT_RULES = {"performer-split", "performer-author", "ensemble-expanded",
              "punctuation-spacing", "ellipsis-normalized", "mixed-script",
              "abbreviation-normalized", "typo-corrected", "name-unified"}

# The export abbreviates the broadcasters' house ensembles. Each abbreviation
# is spelled out wherever it stands as a word -- in the performer, and in the
# role the performer was split from ("соло гитара со ТО на РТС"). A single
# pass keeps a replacement from being expanded again; ЗА and ГО are left alone
# because what they stand for is not established. РТЉ is Радио-телевизија
# Љубљана: the ensemble's own uploads name it ("Revijski Orkestar Rtv
# Ljubljana"), which is what settled it where the monograph does not. ГЗО and
# ЗО rest on the same export spelling them out ("Голем забавен оркестар",
# "Забавен оркестар"): the initials are exact and no other ensemble fits them.
# РТ and РТВ are the broadcaster itself, abbreviated the way РТС and МРТ are.
ENSEMBLE_WORDS = {
    "ТО": "Танцов оркестар",
    "РО": "Ревиски оркестар",
    "ГЗО": "Голем забавен оркестар",
    "ЗО": "Забавен оркестар",
    "РТС": "Радио-телевизија Скопје",
    "РТВ": "Радио-телевизија",
    "РТЉ": "Радио-телевизија Љубљана",
    "РТ": "Радио-телевизија",
    "МРТ": "Македонска радио-телевизија",
    "РС": "Радио Скопје",
}
ENSEMBLE_RE = re.compile(
    r"(?<![\w“„])(%s)(?![\w“”])" % "|".join(
        re.escape(k) for k in sorted(ENSEMBLE_WORDS, key=len, reverse=True)))


def expand_ensembles(value):
    """Spell out the ensemble abbreviations in a performer or role string."""
    if not value:
        return value
    return ENSEMBLE_RE.sub(lambda m: ENSEMBLE_WORDS[m.group(1)], value)

# A performer may be followed by an instrument or an accompanying ensemble,
# separated from the name by a comma, a slash or the word "со".
PERFORMER_SEP_RE = re.compile(r"[,/]|\s+со\s+")


def fix_mixed_script(s):
    """Rewrite Latin look-alikes to Cyrillic inside mixed-script words."""
    out = []
    for token in s.split(" "):
        if CYRILLIC_RE.search(token) and LATIN_RE.search(token):
            token = "".join(LATIN_TO_CYRILLIC.get(ch, ch) for ch in token)
        out.append(token)
    return " ".join(out)


def clean_text(value, field):
    """Generic cleanups. Returns (value, list-of-fix-dicts)."""
    s = clean(value)
    if not s:
        return s, []
    changes = {}

    def apply(rule, new):
        nonlocal s
        if new != s:
            if rule in changes:
                changes[rule][1] = new
            else:
                changes[rule] = [s, new]
            s = new

    for rx, rep in ABBREVIATIONS:
        apply("abbreviation-normalized", rx.sub(rep, s))
    if field in ("composer", "performer"):
        apply("punctuation-spacing", re.sub(r"\s*/\s*", " / ", s))
    # missing space after a period that is immediately followed by a letter,
    # e.g. "A.Vivaldi" -> "A. Vivaldi", "Ж.Брел" -> "Ж. Брел"
    apply("punctuation-spacing", re.sub(r"\.(?=[^\W\d_])", ". ", s))
    apply("mixed-script", fix_mixed_script(s))
    apply("ellipsis-normalized", re.sub(r"\.{3,}", "\u2026", s))

    s = re.sub(r"\s+", " ", s).strip()
    fixes = [{"field": field, "rule": rule, "from": pair[0], "to": pair[1]}
             for rule, pair in changes.items()]
    return s, fixes


def apply_maps(value, field):
    """Apply the misspelling and alias maps. Returns (value, fixes)."""
    s = value
    fixes = []
    for rule, table in (("typo-corrected", TYPO_MAP),
                        ("name-unified", NAME_ALIASES)):
        if s in table:
            fixes.append({"field": field, "rule": rule, "from": s, "to": table[s]})
            s = table[s]
    return s, fixes


def split_performer(value):
    """Split a performer into (name, role).

    Trailing parentheses (recording dates, accompanying orchestras) and the
    part after the first comma, slash or "со" become the role; the leading
    name is what the performer facet groups by.

    The trailing parentheses are stripped rather than kept: the role is
    displayed wrapped in brackets by the drawer, so keeping them here renders
    a recording note as "((сним. 1961, ГЗО на РС))". Brackets belong to the
    presentation, and the role is a value the export writes out on its own.
    """
    s = clean(value)
    if not s:
        return s, ""
    role_parts = []
    while True:
        m = re.search(r"\s*\(([^()]*)\)\s*$", s)
        if not m:
            break
        role_parts.insert(0, m.group(1).strip())
        s = s[:m.start()].strip()

    sep = None
    for m in PERFORMER_SEP_RE.finditer(s):
        if s.count("(", 0, m.start()) - s.count(")", 0, m.start()) == 0:
            sep = m
            break
    if sep:
        rest = s[sep.end():].strip()
        s = s[:sep.start()].strip()
        if rest:
            token = sep.group(0).strip()
            if token in (",", "/"):
                role_parts.insert(0, rest)
            else:
                role_parts.insert(0, (token + " " + rest).strip())

    role = ", ".join(p for p in role_parts if p)
    return s, role


def normalize_text(value, field):
    """Clean a free-text field. Returns (value, list-of-fix-dicts)."""
    s, fixes = clean_text(value, field)
    s, extra = apply_maps(s, field)
    return s, fixes + extra


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def find_header(rows):
    for i, row in enumerate(rows):
        if row and row[0].strip() == "наслов":
            return i
    return None


def parse_source(source):
    path = os.path.join(SOURCES_DIR, source["file"])
    columns = source["columns"]
    width = len(columns)
    rows = read_rows(path)
    header_idx = find_header(rows)
    if header_idx is None:
        sys.exit("No header found in {}".format(source["file"]))

    records = []
    for offset, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(cell.strip() for cell in row):
            continue
        row = [clean(c) for c in row]
        # An unquoted comma inside a field (usually the title) creates extra
        # columns; rejoin them into the first field.
        while len(row) > width:
            row = [row[0] + ", " + row[1]] + row[2:]
        while len(row) < width:
            row.append("")
        values = dict(zip(columns, row))

        flags = []
        duration_sec, _ = parse_duration(values.get("minutes", ""), flags)
        signature, collection, _ = normalize_signature(values.get("signature", ""), flags)

        text_fixes = []
        title, fixes = normalize_text(values.get("title", ""), "title")
        text_fixes += fixes
        composer, fixes = normalize_text(values.get("composer", ""), "composer")
        text_fixes += fixes

        performer_full, fixes = clean_text(values.get("performer", ""), "performer")
        text_fixes += fixes
        performer, performer_role = split_performer(performer_full)
        if performer_role:
            text_fixes.append({"field": "performer", "rule": "performer-split",
                               "from": performer_full, "to": performer})
        performer, fixes = apply_maps(performer, "performer")
        text_fixes += fixes

        # After the alias map, so "Забавен анс. на РС" is already a name before
        # "РС" is spelled out.
        expanded = expand_ensembles(performer)
        if expanded != performer:
            text_fixes.append({"field": "performer", "rule": "ensemble-expanded",
                               "from": performer, "to": expanded})
            performer = expanded
        if performer_role:
            expanded_role = expand_ensembles(performer_role)
            if expanded_role != performer_role:
                text_fixes.append({"field": "performer", "rule": "ensemble-expanded",
                                   "from": performer_role, "to": expanded_role})
                performer_role = expanded_role

        if composer == "+++":
            flags.append("composer-placeholder")
            composer = ""

        # The arrangement volumes write "Авторот" where the song's author sang
        # his own piece. It is a pointer, not a performer, so the catalogue
        # names the author the same row credits -- and says so in Забелешки,
        # because the record no longer shows what the export wrote.
        if performer == "Авторот":
            if composer:
                text_fixes.append({"field": "performer", "rule": "performer-author",
                                   "from": performer, "to": composer})
                performer = composer
            else:
                flags.append("missing-performer")
                performer = ""

        if performer == "+++":
            flags.append("performer-placeholder")
            performer = ""
        elif not performer:
            flags.append("missing-performer")

        for fx in text_fixes:
            if fx["rule"] not in flags:
                flags.append(fx["rule"])

        records.append({
            "category": source["category"],
            "title": title,
            "composer": composer,
            "performer": performer,
            "performerRole": performer_role,
            "durationSec": duration_sec,
            "durationRaw": values.get("minutes", ""),
            "signature": signature,
            "signatureRaw": values.get("signature", ""),
            "collection": collection,
            "video": None,
            "sourceFile": source["file"],
            "sourceLine": offset,
            "flags": flags,
            "duplicateOf": None,
            "textFixes": text_fixes,
        })
    return records


# ---------------------------------------------------------------------------
# Duplicates, ids, search
# ---------------------------------------------------------------------------
def duplicate_key(rec):
    """The identity two rows have to share to be the same listing.

    Transliterated to a single alphabet so a Latin "O" typed into a Cyrillic
    word (e.g. "ТO на РТС") does not hide a duplicate.
    """
    return (rec["category"], to_latin(rec["title"]), to_latin(rec["performer"]),
            to_latin(rec["signature"] or ""))


def mark_duplicates(records):
    """Flag exact and possible duplicates in place.

    Returns {record id: id of the record it may duplicate}, so the notes can
    point at the twin.
    """
    exact = {}
    base = {}
    possible = {}
    for rec in records:
        key = duplicate_key(rec)
        if key in exact:
            rec["duplicateOf"] = exact[key]
            rec["flags"].append("duplicate")
        else:
            exact[key] = rec["id"]

        weak = (rec["category"], to_latin(rec["title"]), to_latin(rec["performer"]))
        if weak in base and rec["duplicateOf"] is None:
            rec["flags"].append("possible-duplicate")
            possible[rec["id"]] = base[weak]
        base.setdefault(weak, rec["id"])
    return possible


def count_warnings(records):
    """Set warnCount. Has to run after mark_duplicates, which adds flags."""
    for rec in records:
        rec["warnCount"] = sum(1 for f in rec["flags"] if SEVERITY.get(f) == "warning")


TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ѓ": "gj", "е": "e",
    "ж": "zh", "з": "z", "ѕ": "dz", "и": "i", "ј": "j", "к": "k", "л": "l",
    "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "ќ": "kj", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "џ": "dj", "ш": "sh",
}


def to_latin(text):
    return "".join(TRANSLIT.get(ch, ch) for ch in text.lower())


def build_search(rec):
    parts = [rec["title"], rec["performer"], rec["composer"], rec["signature"] or ""]
    cyr = " ".join(p for p in parts if p).lower()
    return "{} {}".format(cyr, to_latin(cyr))


# ---------------------------------------------------------------------------
# YouTube links (sources/youtube.csv)
# ---------------------------------------------------------------------------
# A link is stored as the bare 11-character video id. People paste whatever
# YouTube gave them, so the common URL shapes are accepted and reduced to it.
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
VIDEO_URL_RE = re.compile(
    r"(?:youtu\.be/|youtube(?:-nocookie)?\.com/(?:watch\?(?:[^#\s]*&)?v=|"
    r"embed/|shorts/|live/))([A-Za-z0-9_-]{11})")
YOUTUBE_FILE = "youtube.csv"
REMOVALS_FILE = "removals.csv"


def extract_video_id(value):
    """Return the 11-char video id from a bare id or a pasted YouTube URL."""
    s = clean(value)
    if not s:
        return None
    m = VIDEO_URL_RE.search(s)
    if m:
        return m.group(1)
    return s if VIDEO_ID_RE.match(s) else None


# A machine-found link is only treated as the same recording when the upload's
# own length is within this many seconds of the catalogue's. Mirrored in
# tools/youtube-search.py.
VIDEO_DURATION_TOLERANCE = 5

# A link added on or after this date carries the NEW badge. It is a constant
# rather than a rolling window so that the badge set is a property of the data
# and the build stays reproducible: moving this date forward is what retires a
# badge, and adding a row with a later date is what creates one.
NEW_SINCE = "2026-10-25"

# `added` is written by hand or by tools/youtube-search.py, so it is checked
# rather than trusted: a mistyped date would otherwise compare as a string and
# badge or un-badge a row silently.
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def mmss(seconds):
    """112 -> '1:52'. For the durations a video note compares."""
    if seconds is None or seconds < 0:
        return ""
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


def read_videos():
    """Read the `id,title,video[,found,lengthSec,added]` map. Returns
    ({id: entry}, problems).

    `title` is a human-readable guard: it is not used for matching, but a
    mismatch is reported, because a record's id is positional and would
    otherwise attach a video to the wrong work silently.

    `found` says where a link came from -- `human` (or blank, which is how
    every row written before the column existed reads) for one somebody
    checked, `search` for one tools/youtube-search.py proposed and nobody has
    confirmed. `lengthSec` is the upload's own duration, which is what lets
    the build say how far a machine-found link is from the catalogue's timing.

    `added` is the day the link went in, as `YYYY-MM-DD`. It is a fact about
    the row, so the badge the catalogue shows for "recently added" is derived
    from it rather than from a list kept beside the map, and adding a link
    announces itself. Blank means no date is known, and such a row is never
    badged; a malformed one is reported and read as blank.
    """
    path = os.path.join(SOURCES_DIR, YOUTUBE_FILE)
    if not os.path.exists(path):
        return {}, []
    rows = read_rows(path)
    videos = {}
    problems = []
    for n, row in enumerate(rows, start=1):
        if n == 1 and row and row[0].strip().lower() == "id":
            continue  # header
        if not any(cell.strip() for cell in row):
            continue
        row = [clean(c) for c in row]
        while len(row) < 6:
            row.append("")
        rid, title, raw, found, length = row[0], row[1], row[2], row[3].lower(), row[4]
        added = row[5]
        if not rid:
            problems.append("line {}: empty record id".format(n))
            continue
        video = extract_video_id(raw)
        if not video:
            problems.append("line {}: not a YouTube id or URL: {!r}".format(n, raw))
            continue
        if rid in videos:
            problems.append("line {}: duplicate entry for {}".format(n, rid))
            continue
        if found not in ("", "human", "search"):
            problems.append("line {}: unknown source {!r} (expected human or "
                            "search)".format(n, found))
            found = ""
        if length and not length.isdigit():
            problems.append("line {}: length {!r} is not whole seconds".format(n, length))
            length = ""
        if added:
            try:
                if not DATE_RE.match(added):
                    raise ValueError
                datetime.date.fromisoformat(added)
            except ValueError:
                problems.append("line {}: added {!r} is not a YYYY-MM-DD date".format(
                    n, added))
                added = ""
        videos[rid] = {"title": title, "video": video, "found": found or "human",
                       "lengthSec": int(length) if length else None,
                       "added": added}
    return videos, problems


def attach_videos(records, videos, problems):
    """Fill in rec["video"] and mark the links nobody confirmed.

    A search-found link whose upload runs within VIDEO_DURATION_TOLERANCE of
    the catalogue's timing is treated as the same recording; every other one
    gets the `video-approximate` flag, which the drawer and the notes tab then
    show, and `videoApprox` for the places that only need the boolean. The
    build decides this rather than the finder, so the threshold lives in one
    place and re-running the build reproduces the same marks.
    """
    by_id = {rec["id"]: rec for rec in records}
    for rid in sorted(videos):
        entry = videos[rid]
        rec = by_id.get(rid)
        if rec is None:
            problems.append("unknown record id: {}".format(rid))
            continue
        if entry["title"] and entry["title"] != rec["title"]:
            problems.append(
                "{}: title in youtube.csv is {!r} but the record says {!r}".format(
                    rid, entry["title"], rec["title"]))
        rec["video"] = entry["video"]
        delta = None
        if entry["lengthSec"] is not None:
            rec["videoLengthSec"] = entry["lengthSec"]
            if rec["durationSec"]:
                delta = abs(entry["lengthSec"] - rec["durationSec"])
                rec["videoDeltaSec"] = delta
        if entry["found"] == "search" and (delta is None
                                           or delta > VIDEO_DURATION_TOLERANCE):
            rec["videoApprox"] = True
            rec["flags"].append("video-approximate")
        # The badge is derived from the row's own date, so a link announces
        # itself when it is added and stops when NEW_SINCE moves past it. The
        # build never reads the clock, which is what keeps the payload
        # reproducible across clones and machines.
        if entry["added"] and entry["added"] >= NEW_SINCE:
            rec["isNew"] = True
    return sum(1 for rec in records if rec["video"])


def read_removals():
    """Read the curated `file,line,title,performer,signature,same_as` drop list.

    A listed row is one the source holds twice, so the catalogue carries the
    other copy. `line` is a position in the source file, which is the weakest
    thing to key a deletion on, so the other columns are guards: they are
    checked against the record and a mismatch is reported, never applied.
    `same_as` names the work that is kept, for the one kind of pair the source
    holds twice under two different listings; blank means the copy is an exact
    duplicate and is found by its `duplicate_key()`.
    """
    path = os.path.join(SOURCES_DIR, REMOVALS_FILE)
    if not os.path.exists(path):
        return [], []
    removals = []
    problems = []
    for n, row in enumerate(read_rows(path), start=1):
        if n == 1 and row and row[0].strip().lower() == "file":
            continue  # header
        if not any(cell.strip() for cell in row):
            continue
        row = [clean(c) for c in row]
        while len(row) < 6:
            row.append("")
        file_name, line = row[0], row[1]
        if not file_name or not line.isdigit():
            problems.append("line {}: expected a file name and a line number".format(n))
            continue
        removals.append({"file": file_name, "line": int(line), "title": row[2],
                         "performer": row[3], "signature": row[4],
                         "same_as": row[5]})
    return removals, problems


def drop_rows(records, removals, problems):
    """Drop the listed rows. Returns the [(dropped, kept)] pairs.

    This runs after the ids are handed out, so a drop never renumbers the
    records that stay: an id keeps naming the record it named before, and
    sources/youtube.csv keeps pointing at the works it points at.

    A row goes only when the catalogue is known to carry the same work
    elsewhere, and there are two ways to know it. Either another row shares
    its duplicate key, which is an exact duplicate found on its own, or the
    entry names that row in `same_as` -- a claim that two listings are one
    work, which only a person can make: «Калипсо» is the phonotheque's short
    title for «Играј и пеј калипсо», and nothing in the row says so. The
    pointer has to resolve to exactly one other record in the same category
    with that title; a pointer that matches none or several is reported and
    the row kept, because a wrong drop would take a unique record out of the
    catalogue with no symptom.
    """
    dropped = []
    for entry in removals:
        rec = next((r for r in records if r["sourceFile"] == entry["file"]
                    and r["sourceLine"] == entry["line"]), None)
        if rec is None:
            problems.append("{}: no row at line {}".format(entry["file"], entry["line"]))
            continue
        for field in ("title", "performer", "signature"):
            if entry[field] and entry[field] != rec[field]:
                problems.append("{} line {}: {} is {!r}, not {!r}".format(
                    entry["file"], entry["line"], field, rec[field], entry[field]))
                rec = None
                break
        if rec is None:
            continue
        if entry["same_as"]:
            title = to_latin(entry["same_as"])
            twins = [r for r in records if r is not rec
                     and r["category"] == rec["category"]
                     and to_latin(r["title"]) == title]
            if len(twins) != 1:
                problems.append(
                    "{} line {}: same_as {!r} names {} rows, not one".format(
                        entry["file"], entry["line"], entry["same_as"], len(twins)))
                continue
            twin = twins[0]
        else:
            key = duplicate_key(rec)
            twin = next((r for r in records if r is not rec
                         and duplicate_key(r) == key), None)
            if twin is None:
                problems.append("{} line {}: no other row duplicates it".format(
                    entry["file"], entry["line"]))
                continue
        records.remove(rec)
        dropped.append((rec, twin))
    return dropped


# ---------------------------------------------------------------------------
# The static catalogue page
# ---------------------------------------------------------------------------
# index.html is an app: the works arrive only after app.js fetches
# data/catalog.js and builds the table, so a crawler that runs no scripts reads
# a shell and nothing else. This page is the same catalogue as one plain
# document, generated from the records above so it cannot drift from them, and
# committed like data/*.
#
# Its Macedonian prose is the one place the project's "every string comes from
# assets/i18n.js" rule cannot hold: the page has to carry text with no script to
# put it there. The labels below mirror the mk values of app.title, app.subtitle,
# app.credit, cat.*, col.*, privacy.link and common.none; change both together.
# Everything else — titles, performers, composers, durations, signatures and the
# counts — is read from the data, so a number written here cannot go stale.
SITE = "https://shpato.gocemitevski.com"
PAGE_FILE = "dela.html"
PAGE_TEXT = {
    "title": "Сите дела на Драган Ѓаконовски – Шпато во фонотеката на МРТВ",
    "description": (
        "Целосен список на делата на Драган Ѓаконовски – Шпато во фонотеката "
        "на МРТВ, по категорија, со изведувач, времетраење и сигнатура."
    ),
    "name": "Драган Ѓаконовски – Шпато",
    "subtitle": "Целосен список на делата во фонотеката на МРТВ",
    "heading": "Делата на Драган Ѓаконовски – Шпато",
    "lead": (
        "Ова е целосниот список на делата на Драган Ѓаконовски – Шпато во "
        "фонотеката на Македонската радио-телевизија, подреден по категорија — "
        "вкупно {n}. Податоците се преземени од монографијата на Ванчо "
        "Димитров и се истите што ги прикажува интерактивниот каталог, каде "
        "што може да се пребарува, филтрира и слуша снимка."
    ),
    "openApp": "Отвори го интерактивниот каталог",
    "contents": "Содржина",
    "columns": ["Наслов", "Изведувач", "Автор", "Времетраење", "Сигнатура"],
    "caption": "{} во фонотеката на МРТВ",
    "credit": "Изработено од",
    "authorName": "Гоце Митевски",
    "privacy": "Приватност",
    "allWorks": "Сите дела на Шпато",
    "none": "—",
    "selfAuthor": "Драган Ѓаконовски – Шпато",
    # The shell around the list, so the page reads as the same site as the app.
    # It is the header and the footer; the tab strip is not here, because this
    # is one document rather than four views, and its TOC already lists what is
    # on it. There is no language switch either: the page and everything it
    # lists are Macedonian.
    "skip": "Прескокни до содржината",
    "theme": "Тема",
    "themeLight": "Светла",
    "themeDark": "Темна",
    "shareLabel": "Сподели",
    "shareX": "Сподели на „X“",
    "shareFacebook": "Сподели на „Facebook“",
    "shareLinkedin": "Сподели на „LinkedIn“",
    "shareBluesky": "Сподели на „Bluesky“",
    "categories": {
        "vocal": "Вокални композиции",
        "instrumental": "Инструментални композиции",
        "arrThemes": "Аранжмани на теми од други автори",
        "arrVocal": "Аранжмани на вокални творби од други автори",
    },
}

# The theme line index.html runs before first paint, minus the two boot classes:
# the page has no app to wait for. Duplicated rather than shared, because
# sharing it would cost a request and this is six lines that must run
# synchronously in the head. Change both together.
PAGE_THEME_SCRIPT = """  <script>
    /* Apply the saved theme before first paint, so a reader who chose the dark
       theme in the app does not get a white flash here. */
    (function () {
      try {
        var saved = localStorage.getItem("shpato-theme");
        var theme = saved || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
        document.documentElement.setAttribute("data-theme", theme);
      } catch (e) {}
    })();
  </script>"""

# The glyphs the shell needs. index.html's are inline too, but there they sit in
# the document; this page is generated, so the paths live here. The theme pair is
# the app's two toggle icons, and the four share glyphs are Simple Icons (CC0),
# the same ones assets/app.js and index.html carry. Change them together.
PAGE_THEME_ICONS = {
    "light": '<circle cx="12" cy="12" r="4.6"/>'
             '<path d="M12 2.4v2.2M12 19.4v2.2M2.4 12h2.2M19.4 12h2.2'
             'M5.2 5.2l1.6 1.6M17.2 17.2l1.6 1.6M18.8 5.2l-1.6 1.6M6.8 17.2l-1.6 1.6"/>',
    "dark": '<path d="M21 13.1A9 9 0 1 1 10.9 3.1 7.4 7.4 0 0 0 21 13.1Z"/>',
}
PAGE_SHARE_ICONS = [
    ("x", "shareX",
     "M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33"
     "l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929"
     " 1.329 7.754 11.09h-3.182z"),
    ("facebook", "shareFacebook",
     "M9.101 23.691v-7.98H6.627v-3.667h2.474v-1.58c0-4.085 1.848-5.978 5.858-5.978.401 0"
     " .955.042 1.468.103a8.68 8.68 0 0 1 1.141.195v3.325a8.623 8.623 0 0 0-.653-.036"
     " 26.805 26.805 0 0 0-.733-.009c-.707 0-1.259.096-1.675.309a1.686 1.686 0 0 0-.679.622"
     "c-.258.42-.374.995-.374 1.752v1.297h3.919l-.386 2.103-.287 1.564h-3.246v8.245"
     "C19.396 23.238 24 18.179 24 12.044c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.628"
     " 3.874 10.35 9.101 11.647Z"),
    ("linkedin", "shareLinkedin",
     "M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136"
     " 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267"
     " 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063"
     " 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782"
     " 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792"
     " 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"),
    ("bluesky", "shareBluesky",
     "M5.202 2.857C7.954 4.922 10.913 9.11 12 11.358c1.087-2.247 4.046-6.436 6.798-8.501"
     "C20.783 1.366 24 .213 24 3.883c0 .732-.42 6.156-.667 7.037-.856 3.061-3.978 3.842-6.755"
     " 3.37 4.854.826 6.089 3.562 3.422 6.299-5.065 5.196-7.28-1.304-7.847-2.97-.104-.305-.152"
     "-.448-.153-.327 0-.121-.05.022-.153.327-.568 1.666-2.782 8.166-7.847 2.97-2.667-2.737"
     "-1.432-5.473 3.422-6.3-2.777.473-5.899-.308-6.755-3.369C.42 10.04 0 4.615 0 3.883c0"
     "-3.67 3.217-2.517 5.202-1.026"),
]

# The ordering app.js uses by default: the Macedonian alphabet in order, then
# Latin, with a space ahead of punctuation and digits ahead of both. Ported from
# compareText()/collationRank() so the static list and the app's first column
# agree — the two browsers that disagreed once are the reason that comparator
# exists at all. Keep the two in step.
MK_ORDER = "абвгдѓежзѕијклљмнњопрстќуфхцчџш"
LATIN_ORDER = "abcdefghijklmnopqrstuvwxyz"
DIGIT_ORDER = "0123456789"
LATIN_FOLD = {
    "à": "a", "á": "a", "â": "a", "ä": "a", "å": "a", "æ": "ae", "ç": "c",
    "è": "e", "é": "e", "ê": "e", "ë": "e", "ì": "i", "í": "i", "î": "i",
    "ï": "i", "ñ": "n", "ò": "o", "ó": "o", "ô": "o", "ö": "o", "ø": "o",
    "ù": "u", "ú": "u", "û": "u", "ü": "u", "ý": "y", "š": "s", "ž": "z",
    "č": "c", "ć": "c", "đ": "d",
}


def esc(value):
    return html.escape(value or "", quote=False)


def collate_fold(text):
    return "".join(LATIN_FOLD.get(ch, ch) for ch in (text or "").lower())


def collation_rank(ch):
    index = MK_ORDER.find(ch)
    if index != -1:
        return index
    index = LATIN_ORDER.find(ch)
    if index != -1:
        return 60 + index
    index = DIGIT_ORDER.find(ch)
    if index != -1:
        return 10 + index
    if ch == " ":
        return 1
    if "\u0400" <= ch <= "\u04ff":
        return 55
    if ch < "\u0080":
        return 2
    return 90


def collate_key(text):
    folded = collate_fold(text)
    return (tuple(collation_rank(ch) for ch in folded), len(folded), folded)


def page_row(rec):
    """One work as a table row: the title names the row, the rest are cells."""
    composer = rec["composer"] or ""
    if not composer and rec["category"] in ("vocal", "instrumental"):
        # The two volumes of his own compositions carry no author column at all,
        # so their cells are empty because the volume is the author. The app
        # fills that in adoptData(); the static page has to fill it the same way
        # or the column would contradict the table the reader came from.
        composer = PAGE_TEXT["selfAuthor"]
    duration = PAGE_TEXT["none"] if rec["durationSec"] is None else mmss(rec["durationSec"])
    return (
        '<tr><th scope="row" class="cell-title">{title}</th>'
        '<td class="cell-perf">{performer}</td>'
        '<td class="cell-comp">{composer}</td>'
        '<td class="dur">{duration}</td>'
        '<td class="sig">{signature}</td></tr>'
    ).format(
        title=esc(rec["title"]),
        performer=esc(rec["performer"] or PAGE_TEXT["none"]),
        composer=esc(composer),
        duration=duration,
        signature=esc(rec["signature"] or rec.get("signatureRaw") or PAGE_TEXT["none"]),
    )


def write_catalog_page(records, meta):
    columns = "".join('<th scope="col">{}</th>'.format(esc(col))
                      for col in PAGE_TEXT["columns"])
    contents = []
    sections = []
    for source in SOURCES:
        category = source["category"]
        rows = [rec for rec in records if rec["category"] == category]
        rows.sort(key=lambda rec: collate_key(rec["title"]))
        label = PAGE_TEXT["categories"][category]
        anchor = "cat-" + category
        heading = "h-" + category
        contents.append(
            '<li><a href="#{anchor}">{label}</a>'
            ' <span class="doc-count">{n}</span></li>'.format(
                anchor=anchor, label=esc(label), n=len(rows)))
        sections.append(
            '<section class="doc-section" id="{anchor}" aria-labelledby="{heading}">\n'
            '  <h2 id="{heading}">{label} <span class="doc-count">{n}</span></h2>\n'
            '  <div class="table-frame">\n'
            # The card is the scroller and holds no focusable row, so a keyboard
            # could not pan it at all; tabindex makes the card itself a stop and
            # the arrow keys reach the columns a phone hides.
            '    <div class="table-wrap doc-table" tabindex="0">\n'
            '      <table class="catalog-table">\n'
            '        <caption class="visually-hidden">{caption}</caption>\n'
            '        <thead><tr>{columns}</tr></thead>\n'
            '        <tbody>\n{rows}\n        </tbody>\n'
            '      </table>\n'
            '    </div>\n'
            '    <div class="pan-cue left" aria-hidden="true"></div>\n'
            '    <div class="pan-cue right" aria-hidden="true"></div>\n'
            '  </div>\n'
            '</section>\n'.format(
                anchor=anchor, heading=heading, label=esc(label), n=len(rows),
                caption=esc(PAGE_TEXT["caption"].format(label)),
                columns=columns,
                rows="\n".join("          " + page_row(rec) for rec in rows)))

    title = esc(PAGE_TEXT["title"])
    description = esc(PAGE_TEXT["description"])
    url = SITE + "/" + PAGE_FILE
    cover = SITE + "/assets/images/Dragan-Gjakonovski-Shpato-Cover.png"
    lines = [
        "<!doctype html>",
        '<html lang="mk">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        "  <title>{}</title>".format(title),
        '  <meta name="description" content="{}">'.format(description),
        "  <!-- The catalogue as one plain document, so a crawler that runs no",
        "       scripts still reads the works. It is its own page rather than a",
        "       copy of the app: this one is canonical for this address, and the",
        "       app stays canonical for the root it is shared by. -->",
        '  <link rel="canonical" href="{}">'.format(url),
        '  <meta name="robots" content="index, follow, max-image-preview:large">',
        '  <meta property="og:type" content="website">',
        '  <meta property="og:site_name" content="{}">'.format(esc(PAGE_TEXT["name"])),
        '  <meta property="og:url" content="{}">'.format(url),
        '  <meta property="og:title" content="{}">'.format(title),
        '  <meta property="og:description" content="{}">'.format(description),
        '  <meta property="og:locale" content="mk_MK">',
        '  <meta property="og:image" content="{}">'.format(cover),
        '  <meta property="og:image:type" content="image/png">',
        '  <meta property="og:image:width" content="1920">',
        '  <meta property="og:image:height" content="1080">',
        '  <meta name="twitter:card" content="summary_large_image">',
        '  <meta name="twitter:title" content="{}">'.format(title),
        '  <meta name="twitter:description" content="{}">'.format(description),
        '  <meta name="twitter:image" content="{}">'.format(cover),
        '  <link rel="icon" href="assets/images/favicon.ico" sizes="16x16 32x32 48x48">',
        '  <link rel="icon" href="assets/images/favicon-32.png" type="image/png" sizes="32x32">',
        '  <link rel="icon" href="assets/images/favicon-16.png" type="image/png" sizes="16x16">',
        '  <link rel="apple-touch-icon" href="assets/images/apple-touch-icon.png">',
        # The browser chrome colour the app sets from CSS too; doc.js syncs it
        # once the stylesheet has resolved --theme-color.
        '  <meta name="theme-color" content="#0d1117">',
    ]
    lines.extend(PAGE_THEME_SCRIPT.splitlines())
    lines.extend([
        '  <link rel="stylesheet" href="assets/styles.min.css">',
        "</head>",
        '<body class="catalog-doc">',
        '  <a class="skip-link" href="#main">{}</a>'.format(esc(PAGE_TEXT["skip"])),
        "",
        '  <header class="site-header">',
        # The app links the root, because that is where Pages serves it. This
        # page is also read from disk, where "./" is a directory listing, and it
        # carries no script to tell the difference — so it names the document
        # itself. On the web that is the same page index.html's canonical folds
        # into the root.
        '    <a class="brand" href="index.html">',
        '      <span class="brand-mark" aria-hidden="true">',
        '        <img src="assets/images/Dragan-Gjakonovski-Shpato-Icon-168.webp" alt="" width="168" height="168">',
        "      </span>",
        '      <span class="brand-text">',
        '        <span class="brand-name">{}</span>'.format(esc(PAGE_TEXT["name"])),
        '        <span class="brand-sub">{}</span>'.format(esc(PAGE_TEXT["subtitle"])),
        "      </span>",
        "    </a>",
        # No language switch: the page and the catalogue in it are Macedonian.
        # The theme switch is the app's, and doc.js makes it work.
        '    <div class="header-actions">',
        '      <div class="theme-toggle" role="group" aria-label="{}">'.format(
            esc(PAGE_TEXT["theme"])),
    ])
    for theme in ("light", "dark"):
        label = PAGE_TEXT["themeLight" if theme == "light" else "themeDark"]
        lines.extend([
            '        <button type="button" data-theme="{theme}" aria-pressed="false"'
            ' aria-label="{label}" title="{label}">'.format(theme=theme, label=esc(label)),
            '          <svg class="toggle-icon" viewBox="0 0 24 24" aria-hidden="true"'
            ' focusable="false">{}</svg>'.format(PAGE_THEME_ICONS[theme]),
            "        </button>",
        ])
    lines.extend([
        "      </div>",
        "    </div>",
        "  </header>",
        "",
        '  <main id="main" tabindex="-1">',
        "    <h1>{}</h1>".format(esc(PAGE_TEXT["heading"])),
        '    <p class="doc-lead">{}</p>'.format(
            esc(PAGE_TEXT["lead"].format(n=meta["total"]))),
        '    <p class="doc-cta"><a class="btn" href="index.html">{}</a></p>'.format(
            esc(PAGE_TEXT["openApp"])),
        '    <nav class="doc-toc" aria-labelledby="doc-contents">',
        '      <p class="doc-toc-title" id="doc-contents">{}</p>'.format(
            esc(PAGE_TEXT["contents"])),
        "      <ul>",
    ])
    lines.extend("        " + item for item in contents)
    lines.extend(["      </ul>", "    </nav>", ""])
    for section in sections:
        lines.extend("    " + line for line in section.splitlines())
        lines.append("")
    lines.extend([
        '    <p class="doc-cta"><a class="btn" href="index.html">{}</a></p>'.format(
            esc(PAGE_TEXT["openApp"])),
        "  </main>",
        "",
        '  <footer class="site-footer">',
        '    <p class="footer-credit">',
        "      {}".format(esc(PAGE_TEXT["credit"])),
        '      <a href="https://www.gocemitevski.com" target="_blank" rel="noopener">{}</a>.'.format(
            esc(PAGE_TEXT["authorName"])),
        # The app's two doors that are not tabs. This is the full list, so its
        # door says where the reader already is instead of linking to itself.
        '      <span class="link-btn footer-current" aria-current="page">{}</span>'.format(
            esc(PAGE_TEXT["allWorks"])),
        '      <a class="link-btn" href="index.html#tab=privacy">{}</a>'.format(
            esc(PAGE_TEXT["privacy"])),
        "    </p>",
        # The app's share intents. doc.js fills the hrefs from this page's
        # canonical address, because opened from disk a file: URL means nothing
        # to whoever receives it.
        '    <div class="footer-share" role="group" aria-label="{}">'.format(
            esc(PAGE_TEXT["shareLabel"])),
    ])
    for key, label_key, path in PAGE_SHARE_ICONS:
        lines.extend([
            '      <a id="share-{key}" target="_blank" rel="noopener"'
            ' aria-label="{label}">'.format(key=key, label=esc(PAGE_TEXT[label_key])),
            '        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
            '          <path d="{}"/>'.format(path),
            "        </svg>",
            "      </a>",
        ])
    lines.extend([
        "    </div>",
        "  </footer>",
        # The page's only script: the works are in the HTML, so this carries the
        # controls that need one — the theme switch, the share hrefs and the pan
        # cue — and nothing else.
        '  <script src="assets/doc.min.js"></script>',
        "</body>",
        "</html>",
        "",
    ])
    with open(os.path.join(ROOT, PAGE_FILE), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    all_records = []
    for source in SOURCES:
        all_records.extend(parse_source(source))

    # stable ids per category
    per_cat = {}
    for rec in all_records:
        n = per_cat.get(rec["category"], 0) + 1
        per_cat[rec["category"]] = n
        rec["id"] = "{}-{:04d}".format(rec["category"], n)

    # Rows the source holds twice, dropped after the ids above were handed out
    # so nothing is renumbered. The notes below record every drop.
    removals, removal_problems = read_removals()
    dropped_rows = drop_rows(all_records, removals, removal_problems)

    counters = {}
    for rec in all_records:
        counters[rec["category"]] = counters.get(rec["category"], 0) + 1

    possible_duplicates = mark_duplicates(all_records)
    count_warnings(all_records)
    for rec in all_records:
        rec["search"] = build_search(rec)

    videos, video_problems = read_videos()
    video_count = attach_videos(all_records, videos, video_problems)

    # The links marked new in the map itself; see read_videos.
    new_count = sum(1 for rec in all_records if rec.get("isNew"))

    # data notes
    notes = []
    for rec in all_records:
        for fx in rec["textFixes"]:
            notes.append({
                "id": rec["id"],
                "category": rec["category"],
                "title": rec["title"],
                "sourceFile": rec["sourceFile"],
                "sourceLine": rec["sourceLine"],
                "rule": fx["rule"],
                "severity": SEVERITY.get(fx["rule"], "info"),
                "field": fx["field"],
                "raw": fx["from"],
                "normalized": fx["to"],
            })
        for rule in rec["flags"]:
            if rule in TEXT_RULES:
                continue
            if rule.startswith("signature"):
                raw, normalized = rec["signatureRaw"], rec["signature"]
            elif rule.startswith("duration"):
                raw, normalized = rec["durationRaw"], rec["durationSec"]
            elif rule == "composer-placeholder":
                raw, normalized = "+++", ""
            elif rule == "duplicate":
                raw, normalized = rec["title"], rec["duplicateOf"] or ""
            elif rule == "possible-duplicate":
                raw, normalized = rec["title"], possible_duplicates.get(rec["id"]) or ""
            elif rule == "video-approximate":
                # The two durations the reader can compare: ours, and the
                # found upload's ("?" when the finder never learned it).
                raw = mmss(rec["durationSec"])
                normalized = mmss(rec.get("videoLengthSec")) or "?"
            else:
                raw, normalized = "", ""
            entry = {
                "id": rec["id"],
                "category": rec["category"],
                "title": rec["title"],
                "sourceFile": rec["sourceFile"],
                "sourceLine": rec["sourceLine"],
                "rule": rule,
                "severity": SEVERITY.get(rule, "info"),
                "raw": raw,
                "normalized": normalized,
            }
            notes.append(entry)

    # A dropped row is a normalization like any other. Without a note the
    # catalogue would just be one record shorter than the source and nothing
    # would say which row went or why.
    for dropped, kept in dropped_rows:
        notes.append({
            "id": dropped["id"],
            "category": dropped["category"],
            "title": dropped["title"],
            "sourceFile": dropped["sourceFile"],
            "sourceLine": dropped["sourceLine"],
            "rule": "duplicate-dropped",
            "severity": SEVERITY["duplicate-dropped"],
            "raw": dropped["title"],
            "normalized": kept["id"],
        })

    # No build timestamp: it would make the committed output non-reproducible.
    meta = {
        "total": len(all_records),
        "counts": counters,
        "notes": len(notes),
        "videos": video_count,
        "new": new_count,
        "source": "https://issuu.com/mareperotrpovski/docs/spato_kompaktna_verzija",
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    write_json(os.path.join(DATA_DIR, "catalog.json"),
               {"meta": meta, "records": all_records})
    write_json(os.path.join(DATA_DIR, "notes.json"),
               {"meta": meta, "notes": notes})
    write_js(os.path.join(DATA_DIR, "catalog.js"), "CATALOG",
             {"meta": meta, "records": all_records})
    write_js(os.path.join(DATA_DIR, "notes.js"), "NOTES",
             {"meta": meta, "notes": notes})
    # The plain document a crawler that runs no scripts can read. It is built
    # from the records, not from the payload, so it cannot drift from the table.
    write_catalog_page(all_records, meta)
    # The hand-written assets are minified into siblings, which index.html
    # points at; the generated data files are already written compact and are
    # left alone. Same command, so nothing can go stale on its own.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import minify
    minify.main([])

    expected = {"vocal": 73, "instrumental": 55, "arrThemes": 43, "arrVocal": 260}
    print("Built {} records: {}".format(len(all_records), counters))
    print("Expected:            {}".format(expected))
    print("Notes: {}".format(len(notes)))
    print("Videos: {} of {}".format(video_count, len(all_records)))
    print("New: {} of {}".format(new_count, len(all_records)))
    print("Dropped: {} row(s) the source repeats".format(len(dropped_rows)))
    for problem in removal_problems:
        print("WARNING removals.csv: {}".format(problem), file=sys.stderr)
    for problem in video_problems:
        print("WARNING youtube.csv: {}".format(problem), file=sys.stderr)
    if counters != expected:
        print("WARNING: counts differ from expectation", file=sys.stderr)


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def write_js(path, global_name, payload):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("window.{0} = ".format(global_name))
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")


if __name__ == "__main__":
    main()
