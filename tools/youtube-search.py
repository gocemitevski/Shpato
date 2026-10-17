#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find candidate YouTube videos for the catalogue's works.

This is a convenience for filling in `sources/youtube.csv`, not part of the
build. `tools/build.py` reads that file; this script writes nothing.

It queries YouTube's public search page and prints the results for a human to
review. It never decides on its own: the suggestions are ranked by YouTube, not
verified, and a wrong link is worse than a missing one.

A work is searched with its title and performer. Only when that returns
nothing that looks like the work does the search widen: the same terms
romanised, then the title without the performer.

That order is measured, not guessed. Against the 23 links already curated, the
title+performer query returns the right video for all 23 (twenty of them as the
top hit), romanising it returns 22, and dropping the performer returns 13 --
because 38 catalogue titles are shared by more than one work. YouTube matches
across scripts on its own, so the romanised form is a fallback for the works
the first query misses, not a routine second search. Which query returned the
results is always printed.

    python3 tools/youtube-search.py                     # first 25 unlinked works
    python3 tools/youtube-search.py --limit 50 --skip 25
    python3 tools/youtube-search.py --ids vocal-0001 instrumental-0007
    python3 tools/youtube-search.py --category vocal --limit 10
    python3 tools/youtube-search.py --query "Нина Спирова Еден бакнеж"
    python3 tools/youtube-search.py --csv --limit 25     # ready-to-paste lines
    python3 tools/youtube-search.py --exhaustive --ids vocal-0009

`--limit` and `--skip` page through the catalogue scan; `--ids` is an explicit
selection and ignores both. A work that already has a video is skipped by the
scan (`--ids` still reports it), so paging through a batch and confirming links
as you go makes progress.

Review the output, then paste the confirmed lines into `sources/youtube.csv`
and re-run the build. Only the Python 3 standard library is used.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "data", "catalog.json")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Reuse the build's transliteration rather than growing a third copy of it:
# it already romanises the way uploaders actually type (Ѓаконовски ->
# gjakonovski, Шпато -> shpato).
from build import to_latin  # noqa: E402

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
INITIAL_DATA_RE = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)

# Words that say nothing about which recording this is, so they must not make
# a candidate look like a match on their own.
NOISE_WORDS = {"the", "and", "feat", "ft", "official", "video", "audio", "hd",
               "live", "records", "album", "song"}

_LAST_FETCH = [0.0]


def load_records():
    if not os.path.exists(CATALOG):
        sys.exit("{} is missing; run tools/build.py first".format(CATALOG))
    with open(CATALOG, encoding="utf-8") as fh:
        return json.load(fh)["records"]


def fetch(query):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "mk,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def paced_fetch(query, delay):
    """fetch(), but never more often than `delay` seconds across the run."""
    if delay:
        wait = delay - (time.time() - _LAST_FETCH[0])
        if wait > 0:
            time.sleep(wait)
    try:
        return fetch(query)
    finally:
        _LAST_FETCH[0] = time.time()


def _walk(node, out):
    if isinstance(node, dict):
        if "videoRenderer" in node and isinstance(node["videoRenderer"], dict):
            out.append(node["videoRenderer"])
        for value in node.values():
            _walk(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk(value, out)


def _text(node, key):
    node = node.get(key) or {}
    if "simpleText" in node:
        return node["simpleText"]
    runs = node.get("runs") or [{}]
    return runs[0].get("text", "")


def parse(html):
    """Return [{id, title, channel, length}] from a search results page."""
    m = INITIAL_DATA_RE.search(html)
    renderers = []
    if m:
        try:
            _walk(json.loads(m.group(1)), renderers)
        except ValueError:
            renderers = []
    if not renderers:
        # Fall back to the flat pattern, which at least yields ids and titles.
        for vid, title in re.findall(
                r'"videoId":"([\w-]{11})".{0,400}?"text":"((?:[^"\\]|\\.)*)"', html):
            try:
                title = json.loads('"' + title + '"')
            except ValueError:
                pass
            renderers.append({"videoId": vid, "title": {"simpleText": title}})
    out = []
    for r in renderers:
        vid = r.get("videoId")
        if not vid or any(v["id"] == vid for v in out):
            continue
        out.append({
            "id": vid,
            "title": _text(r, "title"),
            "channel": _text(r, "ownerText"),
            "length": _text(r, "lengthText"),
        })
    return out


def format_length(seconds):
    if not seconds or seconds < 0:
        return ""
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


def length_seconds(text):
    """'2:32' -> 152, '1:02:03' -> 3723, anything else -> -1."""
    parts = (text or "").split(":")
    if not parts or not all(p.isdigit() for p in parts):
        return -1
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + int(p)
    return seconds


def clean_query(text):
    """YouTube ignores punctuation; drop it rather than let it glue terms."""
    stripped = re.sub(r"[^\w\s]", " ", text or "", flags=re.UNICODE)
    return re.sub(r"\s+", " ", stripped).strip()


def words(text):
    """The significant words of a string, romanised, for comparing."""
    return {w for w in to_latin(clean_query(text)).split() if len(w) > 2} - NOISE_WORDS


def variants_for(title, performer):
    """Query variants for one work, best first, as [(label, query)].

    The first is the query this tool has always used, and it is still the best
    one available: run against the 23 hand-verified links it returns the right
    video for 23 of 23, twenty of them as the top hit. The rest exist only for
    the works it fails on, and they are ordered by what measured as a useful
    fallback -- first the terms again in the Latin script, which some uploads
    are titled in, then without the performer, which measurably costs accuracy
    (13 of 23) because 38 titles are shared by more than one work.

    Anything that repeats an earlier query is dropped, so a work with no
    performer recorded costs no extra search.
    """
    narrow = "title+performer" if performer else "title"
    full = " ".join(p for p in (title, performer) if p)
    out, seen = [], set()
    for label, text in (
            (narrow, full),
            (narrow + ", Latin", to_latin(full)),
            ("title only", title),
            ("title only, Latin", to_latin(title))):
        query = clean_query(text)
        if query and query.lower() not in seen:
            seen.add(query.lower())
            out.append((label, query))
    return out


def variants_for_query(text):
    """Query variants for free text: as typed, then romanised."""
    out, seen = [], set()
    for label, value in (("as typed", text), ("Latin", to_latin(text or ""))):
        query = clean_query(value)
        if query and query.lower() not in seen:
            seen.add(query.lower())
            out.append((label, query))
    return out


def resembles(candidate, wanted):
    """Does a candidate share a real word with the work?

    This only decides whether to widen the search. It never accepts a link --
    a wrong link is worse than a missing one.
    """
    return bool(words(candidate["title"] + " " + candidate["channel"]) & wanted)


def collect(wanted, variants, top, exhaustive, delay):
    """Run the variants in order, stopping as soon as one looks like the work.

    A variant only runs while nothing found so far shares a real word with the
    work, so the common case -- the first query reaching it, which is every one
    of the 23 links already curated -- costs exactly one search, as before.
    `--exhaustive` runs them all regardless.
    """
    tried = []
    for label, query in variants:
        try:
            candidates = parse(paced_fetch(query, delay))[:top]
        except Exception as exc:  # network, or YouTube changed its markup
            print("   search failed: {}  ({})".format(exc, query),
                  file=sys.stderr)
            candidates = []
        tried.append({"label": label, "query": query, "candidates": candidates})
        if exhaustive:
            continue
        if any(resembles(c, wanted) for c in candidates):
            break
    return tried


def works_from_records(records, args):
    if args.ids:
        wanted = set(args.ids)
        picked = [r for r in records if r["id"] in wanted]
        missing = wanted - {r["id"] for r in picked}
        if missing:
            sys.exit("unknown ids: {}".format(", ".join(sorted(missing))))
        # --ids is already an explicit selection, so --limit/--skip (which are
        # for paging the scan) do not apply to it.
    else:
        picked = [r for r in records if not r.get("video")]
        if args.category:
            picked = [r for r in picked if r["category"] == args.category]
        picked = picked[args.skip:args.skip + args.limit]
    return picked


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--query", help="search this text instead of the catalogue")
    ap.add_argument("--ids", nargs="+", metavar="ID", help="record ids to look up")
    ap.add_argument("--category", help="only works in this category")
    ap.add_argument("--limit", type=int, default=25, help="how many works (default 25)")
    ap.add_argument("--skip", type=int, default=0, help="skip this many (for paging)")
    ap.add_argument("--top", type=int, default=3, help="candidates per query (default 3)")
    ap.add_argument("--exhaustive", action="store_true",
                    help="try every variant and show each one's results")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="seconds between searches (default 0.5)")
    ap.add_argument("--csv", action="store_true",
                    help="print the top candidate as an id,title,video line")
    args = ap.parse_args()

    if args.query:
        jobs = [None]
    else:
        jobs = works_from_records(load_records(), args)

    # Real CSV, so a title containing a comma survives being copied into
    # sources/youtube.csv.
    writer = csv.writer(sys.stdout, lineterminator="\n") if args.csv else None

    searched = found = plausible = 0
    for rec in jobs:
        if rec is None:
            title, performer, want = args.query, "", None
            heading = "── {}".format(args.query)
            variants = variants_for_query(args.query)
        else:
            title = rec["title"]
            performer = rec["performer"] or ""
            want = rec["durationSec"]
            heading = "── {}  {}{}".format(
                rec["id"], title, " — " + performer if performer else "")
            variants = variants_for(title, performer)
        if not variants:
            continue
        wanted = words(" ".join([title, performer]))
        print(heading)
        tried = collect(wanted, variants, args.top, args.exhaustive, args.delay)
        for t in tried:
            count = len(t["candidates"])
            print("   {}: «{}» → {}".format(
                t["label"], t["query"],
                "{} candidate{}".format(count, "" if count == 1 else "s")
                if count else "nothing"))

        # One list, so a video found by more than one variant is shown once.
        merged = []
        for t in tried:
            for c in t["candidates"]:
                if not any(m["id"] == c["id"] for m in merged):
                    merged.append(c)

        # The catalogue's duration is the only independent signal available, so
        # a candidate that runs to the same length is marked: it is a strong
        # hint that this is the same recording, not a cover or a different edit.
        for i, c in enumerate(merged, start=1):
            secs = length_seconds(c["length"])
            same = (want is not None and secs > 0 and abs(secs - want) <= 5)
            print("   {}. {}  [{}]{}  {}".format(
                i, c["id"], format_length(secs) or "?",
                "  ≈ catalogue duration" if same else "", c["title"]))
            if c["channel"]:
                print("      {}".format(c["channel"]))
        print("   catalogue duration: {}".format(
            format_length(want) if want else "unknown"))

        searched += 1
        found += 1 if merged else 0
        plausible += 1 if any(resembles(c, wanted) for c in merged) else 0

        if writer and merged:
            writer.writerow([rec["id"] if rec else "",
                             rec["title"] if rec else args.query,
                             merged[0]["id"]])

    # Keep this off stdout so `--csv > file` stays a clean paste-ready file.
    print("searched {} work{}: {} returned a candidate, {} looked like the work"
          .format(searched, "" if searched == 1 else "s", found, plausible),
          file=sys.stderr)


if __name__ == "__main__":
    main()
