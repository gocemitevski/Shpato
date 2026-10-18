#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a normalized catalog from the MRTV phonotheque CSVs.

Reads the four source CSV files (left untouched), normalizes records,
and writes:
  data/catalog.json    - normalized records + meta
  data/catalog.js      - same, as a global for file:// usage
  data/notes.json      - every fix / flag applied, for transparency
  data/notes.js        - same, as a global

It also merges sources/youtube.csv, the hand-curated record -> YouTube video
map (columns `id,title,video`; see the README), into each record's "video"
field.

Only the Python 3 standard library is used.
"""

import csv
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
# and without dots, so it is canonicalised to the plain form.
ABBREVIATIONS = [(re.compile(r"\bТ\.\s*О\.?(?=\s|$)"), "ТО")]
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
TEXT_RULES = {"performer-split", "punctuation-spacing", "ellipsis-normalized",
              "mixed-script", "abbreviation-normalized", "typo-corrected",
              "name-unified"}

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
    """
    s = clean(value)
    if not s:
        return s, ""
    role_parts = []
    while True:
        m = re.search(r"\s*\(([^()]*)\)\s*$", s)
        if not m:
            break
        role_parts.insert(0, "(" + m.group(1).strip() + ")")
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

        if composer == "+++":
            flags.append("composer-placeholder")
            composer = ""

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


def read_videos():
    """Read the curated `id,title,video` map. Returns ({id: video}, problems).

    `title` is a human-readable guard: it is not used for matching, but a
    mismatch is reported, because a record's id is positional and would
    otherwise attach a video to the wrong work silently.
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
        while len(row) < 3:
            row.append("")
        rid, title, raw = row[0], row[1], row[2]
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
        videos[rid] = (title, video)
    return videos, problems


def attach_videos(records, videos, problems):
    """Fill in rec["video"]. Unmatched ids are reported, never guessed."""
    by_id = {rec["id"]: rec for rec in records}
    for rid in sorted(videos):
        title, video = videos[rid]
        rec = by_id.get(rid)
        if rec is None:
            problems.append("unknown record id: {}".format(rid))
            continue
        if title and title != rec["title"]:
            problems.append(
                "{}: title in youtube.csv is {!r} but the record says {!r}".format(
                    rid, title, rec["title"]))
        rec["video"] = video
    return sum(1 for rec in records if rec["video"])


def read_removals():
    """Read the curated `file,line,title,performer,signature` drop list.

    A listed row is one the source holds twice, so the catalogue carries the
    other copy. `line` is a position in the source file, which is the weakest
    thing to key a deletion on, so the other three columns are guards: they are
    checked against the record and a mismatch is reported, never applied.
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
        while len(row) < 5:
            row.append("")
        file_name, line = row[0], row[1]
        if not file_name or not line.isdigit():
            problems.append("line {}: expected a file name and a line number".format(n))
            continue
        removals.append({"file": file_name, "line": int(line),
                         "title": row[2], "performer": row[3], "signature": row[4]})
    return removals, problems


def drop_rows(records, removals, problems):
    """Drop the listed rows. Returns the [(dropped, kept)] pairs.

    This runs after the ids are handed out, so a drop never renumbers the
    records that stay: an id keeps naming the record it named before, and
    sources/youtube.csv keeps pointing at the works it points at. A row is only
    ever dropped when another row shares its duplicate key, because a wrong
    drop would take a unique record out of the catalogue with no symptom.
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
        key = duplicate_key(rec)
        twin = next((r for r in records if r is not rec and duplicate_key(r) == key), None)
        if twin is None:
            problems.append("{} line {}: no other row duplicates it".format(
                entry["file"], entry["line"]))
            continue
        records.remove(rec)
        dropped.append((rec, twin))
    return dropped


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

    expected = {"vocal": 74, "instrumental": 55, "arrThemes": 43, "arrVocal": 261}
    print("Built {} records: {}".format(len(all_records), counters))
    print("Expected:            {}".format(expected))
    print("Notes: {}".format(len(notes)))
    print("Videos: {} of {}".format(video_count, len(all_records)))
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
