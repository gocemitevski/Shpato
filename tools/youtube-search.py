#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find candidate YouTube videos for the catalogue's works.

This is a convenience for filling in `sources/youtube.csv`, not part of the
build. `tools/build.py` reads that file; this script writes nothing.

It queries YouTube's public search page and prints the results for a human to
review. It never decides on its own: the suggestions are ranked by YouTube, not
verified, and a wrong link is worse than a missing one.

    python3 tools/youtube-search.py                     # first 25 unlinked works
    python3 tools/youtube-search.py --limit 50 --skip 25
    python3 tools/youtube-search.py --ids vocal-0001 instrumental-0007
    python3 tools/youtube-search.py --category vocal --limit 10
    python3 tools/youtube-search.py --query "Нина Спирова Еден бакнеж"
    python3 tools/youtube-search.py --csv --limit 25     # ready-to-paste lines

Review the output, then paste the confirmed lines into `sources/youtube.csv`
and re-run the build. Only the Python 3 standard library is used.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "data", "catalog.json")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
INITIAL_DATA_RE = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)


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


def queries_from_records(records, args):
    if args.ids:
        wanted = set(args.ids)
        picked = [r for r in records if r["id"] in wanted]
        missing = wanted - {r["id"] for r in picked}
        if missing:
            sys.exit("unknown ids: {}".format(", ".join(sorted(missing))))
    else:
        picked = [r for r in records if not r.get("video")]
        if args.category:
            picked = [r for r in picked if r["category"] == args.category]
    picked = picked[args.skip:args.skip + args.limit]
    for r in picked:
        yield r, " ".join(p for p in (r["title"], r["performer"]) if p)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--query", help="search this text instead of the catalogue")
    ap.add_argument("--ids", nargs="+", metavar="ID", help="record ids to look up")
    ap.add_argument("--category", help="only works in this category")
    ap.add_argument("--limit", type=int, default=25, help="how many works (default 25)")
    ap.add_argument("--skip", type=int, default=0, help="skip this many (for paging)")
    ap.add_argument("--top", type=int, default=3, help="candidates per work (default 3)")
    ap.add_argument("--csv", action="store_true",
                    help="print the top candidate as an id,title,video line")
    args = ap.parse_args()

    if args.query:
        jobs = [(None, args.query)]
    else:
        jobs = list(queries_from_records(load_records(), args))

    for rec, query in jobs:
        if not query.strip():
            continue
        print("── {} {}".format(rec["id"] if rec else "", query))
        try:
            candidates = parse(fetch(query))[:args.top]
        except Exception as exc:  # network, or YouTube changed its markup
            print("   search failed: {}".format(exc), file=sys.stderr)
            continue
        if not candidates:
            print("   (no results)")
        # The catalogue's duration is the only independent signal available, so
        # a candidate that runs to the same length is marked: it is a strong
        # hint that this is the same recording, not a cover or a different edit.
        want = rec["durationSec"] if rec else None
        for i, c in enumerate(candidates, start=1):
            secs = length_seconds(c["length"])
            same = (want is not None and secs > 0 and abs(secs - want) <= 5)
            print("   {}. {}  [{}]{}  {}".format(
                i, c["id"], format_length(secs) or "?",
                "  ≈ catalogue duration" if same else "", c["title"]))
            if c["channel"]:
                print("      {}".format(c["channel"]))
        print("   catalogue duration: {}".format(
            format_length(want) if want else "unknown"))
        if args.csv and candidates:
            print("{},{},{}".format(
                rec["id"], rec["title"].replace(",", "/"), candidates[0]["id"]))

if __name__ == "__main__":
    main()
