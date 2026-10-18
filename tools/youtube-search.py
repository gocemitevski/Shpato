#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find YouTube videos for the catalogue's works.

This is a convenience for filling in `sources/youtube.csv`, not part of the
build: `tools/build.py` reads that file, this script proposes rows for it and
(with --apply) writes them.

The point of a link here is that the reader can listen to the work, not that
the phonotheque's own copy has been identified. So the question a candidate
has to answer is "is this the same piece of music?", and duration is not
evidence for it: "Blagoja Ceslarov - Aranhuez" runs 90 seconds longer than the
catalogue's timing and is still the right piece. Duration is recorded, and the
build uses it to *mark* a link, never to reject one.

A candidate is accepted when its title carries the work's title and something
ties it to the work's performer or arranger:

  - a distinctive word of the performer's name in the video title;
  - two distinctive words of it anywhere on the page;
  - an upload on a channel a hand-verified link already came from (some works
    only ever appear on an archive channel, with the performer in the title but
    not the uploader);
  - the arranger credited by name (Шпато / Shpato / Gjakonovski).

A title hit means all the significant words of the catalogue title appear in
the candidate's, or at least half of them (two or more) when the title is long
enough to afford it. That is what keeps a shared *title* from being mistaken
for a shared *work*: "Балада за гитара" must not match "Bodulska balada", and
the Serbian "Bez tebe" must not match "Без тебе". Loosening the title test
instead of the artist test is what fills the results with Russian, Serbian and
Slovak songs that merely share a name.

A hand-verified link is written with found=human; anything this script accepts
is written with found=search, and the build records those as an approximate
match (rule video-approximate) unless the upload's own length is within 5
seconds of the catalogue's. Nothing here is silent: --selftest replays the
hand-verified links as if unknown and reports what the rule recovers.

    python3 tools/youtube-search.py --selftest                 # how the rule does
    python3 tools/youtube-search.py --limit 50 --skip 25       # scan, review by eye
    python3 tools/youtube-search.py --ids vocal-0001 --exhaustive
    python3 tools/youtube-search.py --category vocal --limit 10
    python3 tools/youtube-search.py --query "Нина Спирова Еден бакнеж"
    python3 tools/youtube-search.py --report /tmp/links.tsv --limit 400
    python3 tools/youtube-search.py --apply --limit 400        # append accepted rows
    python3 tools/youtube-search.py --backfill                 # fill lengths of known links

`--limit` and `--skip` page through the scan of works without a video; `--ids`
is an explicit selection and ignores both. Only the Python 3 standard library
is used.
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
YOUTUBE_FILE = os.path.join(ROOT, "sources", "youtube.csv")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Reuse the build's transliteration rather than growing a third copy of it:
# it already romanises the way uploaders actually type (Ѓаконовски ->
# gjakonovski, Шпато -> shpato).
from build import to_latin  # noqa: E402

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
INITIAL_DATA_RE = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)
LENGTH_IN_PAGE_RE = re.compile(r'"lengthSeconds":"(\d+)"')
APPROX_MS_RE = re.compile(r'"approxDurationMs":"(\d+)"')
# How close an upload's own length has to be to the catalogue's for the build
# to treat a machine-found link as the same recording. Mirrored in build.py.
CLOSE_ENOUGH_SEC = 5
# An upload may be well off the catalogue's timing and still be the same piece
# (a live take, a different edit), so length never *confirms* a link. But a
# recording cannot be arbitrarily longer or shorter than the work: a 71-minute
# upload of a 3:50 song is a podcast or a full album, and half the length is a
# clip. That is a plausibility test, not a match.
PLAUSIBLE_SLACK_SEC = 120
BRACKETED_RE = re.compile(r"\(([^)]*)\)|\[([^\]]*)\]")
# What a bracketed part of a title may say about an edition without naming the
# work: "(џез верзија)", "(live)", "(instrumental)". A bracket whose words are
# not all in here names the piece a second time instead, and counts.
QUALIFIER_WORDS = {"verzija", "version", "live", "uzivo", "instrumental",
                   "instrumentalna", "remix", "cover", "edit", "mix", "mono",
                   "stereo", "demo", "karaoke", "official", "audio", "video"}
# Short words that change what a title says, so a title never counts as matched
# without them (see `title_words_of`).
NEGATIONS = {"ne", "ni", "bez"}
# An empty results page is how YouTube answers a query it does not want to
# answer as well as one it has no match for; a second, slower ask tells the two
# apart. Only empty pages are retried, so the cost lands on the rarer case. It
# matters because a silent zero is indistinguishable from "not on YouTube" and
# turned one hand-checked link into a self-test miss.
EMPTY_RETRY_DELAY = 1.0

# Words that say nothing about which recording this is, so they must not make
# a candidate look like a match on their own.
NOISE_WORDS = {"the", "and", "feat", "ft", "official", "video", "audio", "hd",
               "live", "records", "album", "song", "topic", "archive"}

# Performer words that name a role rather than a performer: "ТО на РТС" is not
# evidence for a work performed by another RTS orchestra, and РТС alone appears
# on half of YouTube's Macedonian archive. Matching one of these is worth
# nothing, so they are removed before the artist test runs.
ROLE_WORDS = {"orkestar", "orkestarot", "orchestra", "ansambl", "ensemble",
              "trio", "kvartet", "kvintet", "sekstet", "sextet", "hor",
              "chorus", "grupa", "group", "bend", "duo", "solisti", "solist",
              "rts", "mrtv", "tv", "radio", "televizija", "naroden", "zabaven"}

# The arranger's own name, as an uploader would spell it.
CREDIT_WORDS = {"shpato", "gjakonovski", "gjakonovska"}

# Diacritics uploaders drop, on top of the build's Cyrillic transliteration.
FOLD_MAP = str.maketrans({"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d"})

_LAST_FETCH = [0.0]


def load_records():
    if not os.path.exists(CATALOG):
        sys.exit("{} is missing; run tools/build.py first".format(CATALOG))
    with open(CATALOG, encoding="utf-8") as fh:
        return json.load(fh)["records"]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def get(url, delay, tries=2):
    """Fetch a URL, never more often than `delay` seconds across the run.

    One retry, because a single dropped connection should not end a pass that
    is thousands of requests long.
    """
    last = None
    for _ in range(max(1, tries)):
        if delay:
            wait = delay - (time.time() - _LAST_FETCH[0])
            if wait > 0:
                time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept-Language": "mk,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # network, or YouTube changed its markup
            last = exc
        finally:
            _LAST_FETCH[0] = time.time()
    raise last


def search_html(query, delay):
    return get("https://www.youtube.com/results?search_query=" +
               urllib.parse.quote(query), delay)


def oembed(video_id, delay):
    """The upload's own title and channel, via YouTube's oEmbed endpoint."""
    url = ("https://www.youtube.com/oembed?url=" + urllib.parse.quote(
        "https://www.youtube.com/watch?v=" + video_id, safe="") + "&format=json")
    try:
        data = json.loads(get(url, delay))
    except Exception:
        return "", ""
    return data.get("title", ""), data.get("author_name", "")


def oembed_channel(video_id, delay):
    """The uploader's channel name for a video."""
    return oembed(video_id, delay)[1]


def watch_length(video_id, delay):
    """The video's own duration in seconds, or -1."""
    try:
        page = get("https://www.youtube.com/watch?v=" + video_id, delay)
    except Exception:
        return -1
    m = LENGTH_IN_PAGE_RE.search(page)
    if m:
        return int(m.group(1))
    m = APPROX_MS_RE.search(page)
    return int(m.group(1)) // 1000 if m else -1


# ---------------------------------------------------------------------------
# Parsing a results page
# ---------------------------------------------------------------------------
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
        # Fall back to the flat pattern, which at least yields ids, titles and
        # -- within a bounded window -- durations.
        lengths = {}
        for vid, length in re.findall(
                r'"videoId":"([\w-]{11})".{0,600}?"lengthText":\{"simpleText":"([\d:]+)"',
                html):
            lengths.setdefault(vid, length)
        for vid, title in re.findall(
                r'"videoId":"([\w-]{11})".{0,400}?"text":"((?:[^"\\]|\\.)*)"', html):
            try:
                title = json.loads('"' + title + '"')
            except ValueError:
                pass
            renderers.append({"videoId": vid, "title": {"simpleText": title},
                              "lengthText": {"simpleText": lengths.get(vid, "")}})
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
    if seconds is None or seconds < 0:
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


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def clean_query(text):
    """YouTube ignores punctuation; drop it rather than let it glue terms."""
    stripped = re.sub(r"[^\w\s]", " ", text or "", flags=re.UNICODE)
    return re.sub(r"\s+", " ", stripped).strip()


def fold(text):
    """Lowercase ASCII-ish form, for comparing across uploader spellings."""
    return to_latin(clean_query(text)).translate(FOLD_MAP)


def sig_words(text):
    """The significant words of a string: three letters or more, or a number.

    Numbers are significant because they discriminate: "Тема бр. 1" must not
    match "Тема бр. 2".
    """
    return {w for w in fold(text).split() if len(w) >= 3 or w.isdigit()} - NOISE_WORDS


def compare_word(word):
    """Fold the transliteration variants that stand for the same letter.

    The build romanises ч as "ch" and ќ as "kj", and an uploader may write "č"
    (folded to "c") or a plain "k", so "Молчи" arrives as "molchi" against their
    "Molci" and "Ќе наминеш" as "kje" against their "Ke" — one song under two
    spelling conventions. Only comparisons are folded; a query keeps the
    spelling it was built from.
    """
    for digraph, letter in (("ch", "c"), ("sh", "s"), ("zh", "z"), ("kj", "k")):
        word = word.replace(digraph, letter)
    return word


def words_of(text):
    """The comparable words of any text: folded, then digraph-normalised."""
    return set(compare_word(w) for w in fold(text).split())


# The fixed word sets are compared against folded words, so they are folded the
# same way -- otherwise "shpato" in CREDIT_WORDS would never meet the "spato"
# that a page arrives as.
ROLE_WORDS = set(compare_word(w) for w in ROLE_WORDS)
CREDIT_WORDS = set(compare_word(w) for w in CREDIT_WORDS)


def artist_words(performer):
    """The words of a performer that identify the performer, not a role."""
    return set(compare_word(w) for w in sig_words(performer)) - ROLE_WORDS


def title_words_of(text):
    """The words of a title: the significant ones, plus any negation.

    A negation is two letters and would be dropped with the other short words,
    but it is not a word an upload may leave out -- "Не ми верувај" and "Верувај
    ми" are not the same title, and the whole difference is the "не".
    """
    words = set(compare_word(w) for w in sig_words(text))
    for raw in (text or "").split():
        word = compare_word(fold(raw))
        if word in NEGATIONS:
            words.add(word)
    return words


def title_forms(title):
    """The names a work's title goes by, as sets of comparable words.

    A bracketed part of a *work's* title either names the piece a second time —
    "Осаменост (Молчи една долина)" is one piece under two names, and an upload
    will carry one of them — or says how an edition was made ("(џез верзија)",
    "(live)"), which names nothing. Only the second kind is dropped. The first
    form is the title without its brackets; a title matches when any one of its
    forms is present in full.
    """
    text = title or ""
    without = title_words_of(BRACKETED_RE.sub(" ", text))
    forms = [without] if without else []
    for inner in BRACKETED_RE.findall(text):
        words = title_words_of(inner[0] or inner[1])
        if words and words != without and not words <= QUALIFIER_WORDS:
            forms.append(words)
    return forms


def title_words(text):
    """The words of a title as it is written, qualifier brackets dropped."""
    forms = title_forms(text)
    return forms[0] if forms else set()


def word_in(word, have, joined=""):
    """Is this title word in `have`, allowing for an inflected ending?

    "живот" has to meet "животот" and "потонам" its own inflections, or the
    uploads that spell a title out in full would only match sometimes; short
    words are compared exactly, because at three letters a prefix stop is a
    different word as often as it is the same one. `joined` is the candidate's
    own text with the spaces taken out, so that a word the catalogue writes
    solid ("Незнам") still meets an uploader who splits it ("Ne znam").
    """
    for other in have:
        if word == other:
            return True
        if len(word) >= 4 and len(other) >= 4 and (
                word.startswith(other) or other.startswith(word)):
            return True
    return bool(joined) and word in joined


def droppable(word):
    """A title word an upload may leave out: short, and not a number.

    A negation is never droppable, and neither is a number: "Верувај ми" is not
    "Не ми верувај", and "Тема бр. 2" is not "Тема бр. 1".
    """
    return len(word) <= 3 and not word.isdigit() and word not in NEGATIONS


def form_hit(form, have, joined):
    """Is one of a title's names present, word for word?

    A short word may be missing -- an uploader writing "Igraj kalipso" for
    "Играј и пеј калипсо" is not naming a different song, and the same goes for
    a dropped "и" or "во" -- but only in a title of three words or more, so a
    title like "Мојот дом" is not reduced to one word to match on. A word of
    four letters or more carries the name and has to be there, and so does a
    number, which is what keeps "Тема бр. 2" from answering for "Тема бр. 1".
    """
    required = form if len(form) < 3 else [w for w in form if not droppable(w)]
    if not required:
        required = form
    return all(word_in(w, have, joined) for w in required)


def title_hit(title, candidate_title):
    """Does the candidate's title carry the work's title?

    Every significant word of one of the title's names, allowing for a short
    word left out and for an inflected ending. It used to accept half the words
    of a three-word title, which let a different song in on the words it
    happened to share: "Тоше Проески — Сонце во твоите руси коси" matched "Да
    потонам во твоите коси" on "во твоите коси" alone, and the word that names
    the song ("потонам") was the one missing.
    """
    folded = fold(candidate_title or "")
    have = set(compare_word(w) for w in folded.split())
    joined = compare_word(folded.replace(" ", ""))
    return any(form_hit(form, have, joined) for form in title_forms(title))


def plausible_length(record, candidate):
    """Could an upload of this length be this work at all?

    Not evidence that it *is* the work -- only that it could be. Half the
    catalogue's length or less is a clip; more than PLAUSIBLE_SLACK_SEC over it
    is a podcast, a concert or a whole album. Unknown on either side passes,
    since there is nothing to judge.
    """
    want = record.get("durationSec") or 0
    secs = length_seconds(candidate["length"])
    if not want or secs <= 0:
        return True
    return want / 2 <= secs <= want + PLAUSIBLE_SLACK_SEC


def is_trusted(channel, trusted):
    """Is this channel one a hand-verified link already came from?"""
    name = fold(channel)
    if not name:
        return False
    return name in trusted or any(name.startswith(t + " ") for t in trusted)


def accept(record, candidate, trusted):
    """Return the evidence for accepting a candidate, or None.

    The evidence is returned rather than a bare boolean so the same rule can
    explain itself on screen and in --report.
    """
    if not plausible_length(record, candidate):
        return None
    if not title_hit(record["title"], candidate["title"]):
        return None
    words = artist_words(record["performer"] or "")
    title_text = words_of(candidate["title"] or "")
    page_text = title_text | words_of(candidate["channel"])
    # A one-word title ("Илузија") is a weak identity on its own: it then has to
    # be paired with the performer's name in full -- both words of "Зоран
    # Георгиев", which is what keeps a Croatian podcast titled "...najveća
    # iluzija" by a host called Zoran from becoming the song Илузија -- or, when
    # the name is itself one word ("Импулси", a band), with that word. A name
    # with nothing left after the role words leans on the other branches.
    #
    # A trusted channel still stands in for that name. Requiring it anyway was
    # measured over the 122 links a pass had written: it refused 21, and almost
    # all of them were a different *recording of the right song* on a channel a
    # hand-checked link had already come from ("Идила" by Никола Комовски as
    # "Идила - Нина Спирова", "Ти си тој" as "Лидија Кочовска - Ти си тој"),
    # which is the class this catalogue accepts and marks. It is two rows such
    # as "Адиос" becoming "Ljupka Dimitrovska - Adios Amor" that the trade costs,
    # and a wrong song is the worse error, but not at this price.
    need = 2 if len(title_words(record["title"])) == 1 else 1
    need = min(need, len(words))
    if need and len(words & title_text) >= need:
        return {"by": "artist in title", "words": sorted(words & title_text)}
    if is_trusted(candidate["channel"], trusted):
        return {"by": "trusted channel", "words": sorted(words & page_text)}
    if len(words & page_text) >= max(2, need):
        return {"by": "artist words", "words": sorted(words & page_text)}
    credit = CREDIT_WORDS & page_text
    if credit:
        return {"by": "arranger credited", "words": sorted(credit)}
    return None


def performer_core(performer):
    """The performer up to any role after it: 'ТО на РТС, соло X' -> 'ТО на РТС'."""
    head = re.split(r"[,;/]|\bсо\b|\bwith\b", performer or "")[0]
    return " ".join(head.split()[:3])


def variants_for(title, performer):
    """Query variants for one work, best first, as [(label, query)].

    The first query is the one that reaches the most works, measured against
    the hand-verified links. The rest exist for the works it fails on: the
    performer trimmed to its core, both terms and then the title alone in the
    Latin script, the performer alone (an upload may name the song only in its
    description), and finally the arranger's name, which is how a video that
    credits him but not the catalogue's performer is still his work.
    """
    core = performer_core(performer)
    full = " ".join(p for p in (title, performer) if p)
    short = " ".join(p for p in (title, core) if p)
    bare = " ".join(p for p in (title, "Шпато") if p and performer)
    out, seen = [], set()
    for label, text in (
            ("title+performer", full),
            ("title+performer core", short),
            ("title+performer, Latin", to_latin(full)),
            ("title+performer core, Latin", to_latin(short)),
            ("title only", title),
            ("title only, Latin", to_latin(title)),
            ("performer only", performer),
            ("title+Шпато", bare)):
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


def search_candidates(query, top, delay):
    """The candidates a query yields, asked again if it yields none."""
    candidates = []
    for _ in range(2):
        try:
            candidates = parse(search_html(query, delay))[:top]
        except Exception as exc:  # network, or YouTube changed its markup
            print("   search failed: {}  ({})".format(exc, query),
                  file=sys.stderr)
            candidates = []
        if candidates:
            break
        delay += EMPTY_RETRY_DELAY
    return candidates


def collect(record, variants, top, exhaustive, delay, trusted):
    """Run the variants in order, stopping once one yields a candidate.

    Free-text mode and `--exhaustive` run them all regardless.
    """
    tried = []
    for label, query in variants:
        candidates = search_candidates(query, top, delay)
        tried.append({"label": label, "query": query, "candidates": candidates})
        if exhaustive or record is None:
            continue
        if any(accept(record, c, trusted) for c in candidates):
            break
    return tried


def accepted(record, tried, trusted):
    """The accepted candidates across every variant tried, best first.

    Best means closest to the catalogue's own timing, because two uploads of
    the same work are not equally likely to be the one the reader wants; an
    unknown length sorts last. Duration never rejects: it only ranks and, in
    the build, marks.
    """
    merged = []
    for t in tried:
        for c in t["candidates"]:
            if not any(m["id"] == c["id"] for m in merged):
                merged.append(c)
    out = []
    for c in merged:
        evidence = accept(record, c, trusted)
        if not evidence:
            continue
        secs = length_seconds(c["length"])
        want = record.get("durationSec") or 0
        evidence["candidate"] = c
        evidence["lengthSec"] = secs if secs > 0 else -1
        evidence["delta"] = abs(secs - want) if (secs > 0 and want) else None
        out.append(evidence)
    out.sort(key=lambda e: (e["delta"] is None, e["delta"] or 0))
    return merged, out


# ---------------------------------------------------------------------------
# sources/youtube.csv
# ---------------------------------------------------------------------------
def read_youtube():
    """Read `id,title,video[,found,lengthSec]` rows, in file order."""
    rows = []
    if not os.path.exists(YOUTUBE_FILE):
        return rows
    with open(YOUTUBE_FILE, encoding="utf-8-sig", newline="") as fh:
        for n, row in enumerate(csv.reader(fh)):
            if n == 0 and row and row[0].strip().lower() == "id":
                continue
            if not any(cell.strip() for cell in row):
                continue
            row = [c.strip() for c in row] + [""] * 5
            rows.append(row[:5])
    return rows


def write_youtube(rows):
    """Rewrite the file with its header, CRLF like the source it came from."""
    with open(YOUTUBE_FILE, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\r\n")
        writer.writerow(["id", "title", "video", "found", "lengthSec"])
        for row in rows:
            writer.writerow(row)


def channel_cache(rows, delay, cache):
    """Resolve each hand-checked link's uploader, into {video_id: folded channel}.

    Only hand-checked rows: a machine-found link is never evidence for another
    one, so there is no reason to ask YouTube about it.
    """
    for row in rows:
        human = (row[3] or "human").lower() == "human"
        if row[2] and human and row[2] not in cache:
            cache[row[2]] = fold(oembed_channel(row[2], delay))
    return cache


def trusted_channels(rows, exclude, cache):
    """The channels behind the hand-verified links, as a folded set.

    A link this script found is not evidence for the next one -- otherwise one
    tentative link would keep making its channel more trusted -- so only
    `found=human` rows count. `--selftest` passes the link under test's own id
    as `exclude`, so a work cannot be found through the channel its own answer
    came from.
    """
    trusted = set()
    for row in rows:
        rid, video, found = row[0], row[2], (row[3] or "human").lower()
        if found != "human" or not video or rid == exclude:
            continue
        if cache.get(video):
            trusted.add(cache[video])
    return trusted


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
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


def dedupe_picks(picks, used):
    """Keep a video for one work only. Returns {id: (record, hits)}.

    Two catalogue works can share a title -- 38 of them do -- and one upload of
    it can pass the title test for both, the vocal and the instrumental
    arrangement of the same song, say. Only one work can own a video, so the
    first in catalogue order keeps it and the rest lose it visibly rather than
    a link appearing twice under two works.
    """
    out = {}
    for rid, (rec, hits) in picks.items():
        keep = [h for h in hits if h["candidate"]["id"] not in used]
        if not keep:
            print("   {}: {} is already attached to another work".format(
                rid, hits[0]["candidate"]["id"]), file=sys.stderr)
            continue
        used.add(keep[0]["candidate"]["id"])
        out[rid] = (rec, keep)
    return out


def scan(args, rows, cache):
    """Print the candidates for each work; return {record id: (record, hits)}."""
    jobs = [None] if args.query else works_from_records(load_records(), args)
    if args.query:
        trusted = set()
    else:
        channel_cache(rows, args.delay, cache)
        trusted = trusted_channels(rows, None, cache)
        print("trusted channels ({}): {}".format(
            len(trusted), ", ".join(sorted(trusted)) or "none"), file=sys.stderr)

    report = open(args.report, "w", encoding="utf-8", newline="") if args.report else None
    if report:
        report.write("id\ttitle\tperformer\tcandidate\tcandidate title\tchannel"
                     "\tlength\tdelta\tevidence\twords\n")

    picks = {}
    searched = with_candidate = 0
    for rec in jobs:
        if rec is None:
            performer, want = "", None
            print("── {}".format(args.query))
            variants = variants_for_query(args.query)
        else:
            performer = rec["performer"] or ""
            want = rec.get("durationSec")
            print("── {}  {}{}".format(
                rec["id"], rec["title"], " — " + performer if performer else ""))
            variants = variants_for(rec["title"], performer)
        if not variants:
            continue

        tried = collect(rec, variants, args.top, args.exhaustive, args.delay, trusted)
        for t in tried:
            count = len(t["candidates"])
            print("   {}: «{}» → {}".format(
                t["label"], t["query"],
                "{} candidate{}".format(count, "" if count == 1 else "s")
                if count else "nothing"))

        if rec is None:
            seen = []
            for t in tried:
                for c in t["candidates"]:
                    if not any(m["id"] == c["id"] for m in seen):
                        seen.append(c)
            for c in seen[:args.top]:
                print("   - {}  [{}]  «{}»".format(
                    c["id"], c["length"] or "?", c["title"]))
            searched += 1
            continue

        merged, hits = accepted(rec, tried, trusted)
        print("   catalogue duration: {}".format(
            format_length(want) if want else "unknown"))
        if not hits:
            print("   no candidate matches title and artist")
        for ev in hits[:3]:
            c = ev["candidate"]
            print("   ✓ {}  [{}]  Δ {}  {}  «{}»".format(
                c["id"], format_length(ev["lengthSec"]) or "?",
                format_length(ev["delta"]) if ev["delta"] is not None else "?",
                ev["by"], c["title"]))
            print("      {}   ({})".format(
                c["channel"] or "unknown channel", ", ".join(ev["words"]) or "-"))
        if report:
            lines = hits or [None]
            for ev in lines[:3]:
                if ev is None:
                    report.write("\t".join(
                        [rec["id"], rec["title"], performer] + [""] * 6 + ["no match", ""]) + "\n")
                else:
                    c = ev["candidate"]
                    report.write("\t".join(str(v) for v in (
                        rec["id"], rec["title"], performer, c["id"], c["title"],
                        c["channel"], format_length(ev["lengthSec"]),
                        format_length(ev["delta"]) if ev["delta"] is not None else "",
                        ev["by"], ", ".join(ev["words"]))) + "\n")
        if hits:
            picks[rec["id"]] = (rec, hits)
        searched += 1
        with_candidate += 1 if merged else 0

    if report:
        report.close()
    if not args.query:
        picks = dedupe_picks(picks, {row[2] for row in rows if row[2]})
        print("searched {} work{}: {} returned a candidate, {} accepted"
              .format(searched, "" if searched == 1 else "s", with_candidate,
                      len(picks)), file=sys.stderr)
    return picks


def apply_picks(picks, rows):
    """Append the accepted links to sources/youtube.csv, CRLF preserved.

    The record's title goes in as the guard column the build checks against,
    and `found=search` marks the row for the notes pipeline. A row that
    already has a video is never overwritten.
    """
    known = {row[0] for row in rows}
    added = []
    for rid, (rec, hits) in sorted(picks.items()):
        if rid in known:
            continue
        best = hits[0]
        c = best["candidate"]
        rows.append([rid, rec["title"], c["id"], "search",
                     str(best["lengthSec"]) if best["lengthSec"] > 0 else ""])
        added.append((rid, c["id"], best["by"], c["channel"]))
    if added:
        write_youtube(rows)
    print("applied {} link{}".format(len(added), "" if len(added) == 1 else "s"),
          file=sys.stderr)
    for rid, vid, by, channel in added:
        print("   {} → {}  [{}, {}]".format(rid, vid, by, channel), file=sys.stderr)
    return added


def verify(args):
    """Re-apply the acceptance rule to the machine-found rows already in the CSV.

    The rule can tighten after a pass has run -- it did, once a first pass
    attached a 71-minute podcast to a 3:50 song -- and a row that is already
    written down has to be able to answer for itself. This asks YouTube for the
    upload's own title and channel again and runs `accept()` over the row's
    recorded length, so only the rows the rule still refuses come out, instead
    of throwing the pass away and searching the works again. Hand-checked rows
    are never touched, and a row whose upload cannot be fetched is kept and
    reported: a network answer is not a verdict.
    """
    records = {r["id"]: r for r in load_records()}
    rows = read_youtube()
    cache = {}
    channel_cache(rows, args.delay, cache)
    trusted = trusted_channels(rows, None, cache)
    keep, drop, unknown = [], [], []
    seen = 0
    for row in rows:
        rid, video, found = row[0], row[2], (row[3] or "human").lower()
        rec = records.get(rid)
        if found != "search" or not video or rec is None:
            keep.append(row)
            continue
        seen += 1
        title, channel = oembed(video, args.delay)
        if not title:
            unknown.append(row)
            keep.append(row)
            print("   ?     {}  {}  (could not be fetched)".format(rid, video),
                  file=sys.stderr)
            continue
        candidate = {"id": video, "title": title, "channel": channel,
                     "length": format_length(int(row[4])) if row[4].isdigit() else ""}
        evidence = accept(rec, candidate, trusted)
        line = "   {}  {:<16} {:<44} /{}/ [{}] {}".format(
            "keep" if evidence else "drop", rid, title[:44], channel[:24],
            candidate["length"] or "?", evidence["by"] if evidence else "not accepted")
        print(line, file=sys.stderr)
        (keep if evidence else drop).append(row)
    print("verified {} machine-found link{}: {} kept, {} dropped, {} unverifiable".format(
        seen, "" if seen == 1 else "s",
        seen - len(drop) - len(unknown), len(drop), len(unknown)), file=sys.stderr)
    if args.drop and drop:
        write_youtube(keep)
    return drop


def backfill(args):
    """Fill in the length of every known link that has none."""
    rows = read_youtube()
    filled = 0
    for row in rows:
        if not row[2] or row[4]:
            continue
        secs = watch_length(row[2], args.delay)
        if secs > 0:
            row[4] = str(secs)
            filled += 1
        if not row[3]:
            row[3] = "human"
    write_youtube(rows)
    print("backfilled {} of {} link{}".format(
        filled, len(rows), "" if len(rows) == 1 else "s"), file=sys.stderr)
    for row in rows:
        print("   {}  {}  found={}  {}".format(
            row[0], row[2], row[3], format_length(int(row[4])) if row[4] else "?"),
            file=sys.stderr)


def selftest(args, rows, cache):
    """Replay the hand-verified links as if unknown, and report the rule."""
    records = {r["id"]: r for r in load_records()}
    human = [row for row in rows
             if (row[3] or "human").lower() == "human" and row[2]]
    human = human[args.skip:args.skip + args.limit]
    channel_cache(rows, args.delay, cache)
    print("self-test over {} hand-verified links; trusted channels per work are "
          "derived leaving that work's own channel out".format(len(human)))
    recovered = best_hit = 0
    other_count = 0
    for row in human:
        rid, known = row[0], row[2]
        rec = records.get(rid)
        if rec is None:
            print("   {}  (no such record)".format(rid))
            continue
        trusted = trusted_channels(rows, rid, cache)
        variants = variants_for(rec["title"], rec["performer"] or "")
        tried = collect(rec, variants, args.top, True, args.delay, trusted)
        merged, hits = accepted(rec, tried, trusted)
        if not hits:
            # Nothing accepted says as much about YouTube's mood as about the
            # rule: a page that came back empty for a work this time can carry
            # it the next (that is how "На игранка" became a miss in one run and
            # not the next). A work that yields nothing gets one more go before
            # it is called a miss.
            tried = collect(rec, variants, args.top, True, args.delay, trusted)
            merged, hits = accepted(rec, tried, trusted)
        found = any(e["candidate"]["id"] == known for e in hits)
        best = hits[0]["candidate"]["id"] if hits else ""
        other = [e for e in hits if e["candidate"]["id"] != known]
        recovered += 1 if found else 0
        best_hit += 1 if best == known else 0
        other_count += len(other)
        print("   {}  {}  recovered={} accepted={} best={}{}".format(
            "ok  " if found else "MISS", rid, "yes" if found else "NO ", len(hits),
            best, "  (+{} other)".format(len(other)) if other else ""))
        for e in other[:2]:
            c = e["candidate"]
            print("        other: «{}» /{}/ [{}] {}".format(
                c["title"][:60], c["channel"][:26], c["length"] or "?", e["by"]))
    print("self-test: {}/{} recovered, {} as the best pick, {} other candidates "
          "accepted".format(recovered, len(human), best_hit, other_count))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--query", help="search this text instead of the catalogue")
    ap.add_argument("--ids", nargs="+", metavar="ID", help="record ids to look up")
    ap.add_argument("--category", help="only works in this category")
    ap.add_argument("--limit", type=int, default=25, help="how many works (default 25)")
    ap.add_argument("--skip", type=int, default=0, help="skip this many (for paging)")
    ap.add_argument("--top", type=int, default=8, help="candidates per query (default 8)")
    ap.add_argument("--exhaustive", action="store_true",
                    help="try every variant and show each one's results")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="seconds between requests (default 0.5)")
    ap.add_argument("--csv", action="store_true",
                    help="print the accepted rows as id,title,video,found,lengthSec lines")
    ap.add_argument("--report", metavar="PATH",
                    help="write the per-work verdicts as a TSV")
    ap.add_argument("--apply", action="store_true",
                    help="append the accepted links to sources/youtube.csv")
    ap.add_argument("--backfill", action="store_true",
                    help="fill in the length of every known link")
    ap.add_argument("--verify", action="store_true",
                    help="re-apply the rule to the machine-found rows already written down")
    ap.add_argument("--drop", action="store_true",
                    help="with --verify, remove the rows the rule no longer accepts")
    ap.add_argument("--selftest", action="store_true",
                    help="replay the hand-verified links as if unknown")
    args = ap.parse_args()

    if args.apply and args.query:
        sys.exit("--apply needs catalogue works, not --query")
    if args.backfill:
        backfill(args)
        return
    if args.verify:
        verify(args)
        return
    rows = read_youtube()
    cache = {}
    if args.selftest:
        selftest(args, rows, cache)
        return

    picks = scan(args, rows, cache)
    if args.csv:
        writer = csv.writer(sys.stdout, lineterminator="\n")
        for rid, (rec, hits) in sorted(picks.items()):
            best = hits[0]
            writer.writerow([rid, rec["title"], best["candidate"]["id"], "search",
                             best["lengthSec"] if best["lengthSec"] > 0 else ""])
    if args.apply:
        apply_picks(picks, rows)


if __name__ == "__main__":
    main()
