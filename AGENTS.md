# AGENTS.md

Static, dependency-free bilingual (Macedonian/English) catalogue of works by
Dragan Gjakonovski - Shpato held in the MRTV phonotheque.

There is no `package.json`, no bundler, no test runner, no linter and no CI.
The build is Python 3 standard library; the app is browser-native ES5-style
JavaScript. Keep both that way.

## Commands

```bash
python3 tools/build.py          # sources/*.csv -> data/*, dela.html and assets/*.min.{css,js}
python3 -m http.server 8000     # http://localhost:8000/
git status --short              # after a build: must be clean
```

`index.html` also works over `file://`, and that must keep working: no
`fetch()` of local data, no ES modules, no `import`. Generated data is loaded
as plain `<script>` globals.

## Repo map

```
index.html              the whole app shell (five views, drawer)
dela.html               the same catalogue as one plain document, for crawlers
                        (generated, committed)
assets/styles.css       theme tokens + all styling
assets/i18n.js          every user-visible string, mk + en
assets/app.js           all behaviour
assets/doc.js           the static page's few controls (see its section)
assets/*.min.css|.min.js  what index.html loads: generated, committed
assets/fonts/*.woff2    self-hosted Geologica (the only typeface, OFL 1.1)
assets/images/          cover, brand icons, About photograph, favicon set
tools/build.py          normalizer: sources -> data, then the minifier
tools/minify.py         the CSS/JS minifier build.py calls
tools/youtube-search.py candidate finder for the link map (dev-only)
tools/cover.html        1920x1080 social cover render target (dev-only)
tools/favicon.html      favicon render target (dev-only)
data/catalog.json|.js   generated, committed
data/notes.json|.js     generated, committed
sources/*.csv           monograph exports, the build's input
sources/youtube.csv     record -> YouTube video map (checked and machine-found), the build's input
sources/removals.csv    hand-curated rows the source repeats, the build's input
robots.txt              crawl policy (see Deployment)
sitemap.xml             the two canonical URLs (see Deployment)
```

Script order in `index.html` is load-bearing: `assets/i18n.min.js` then
`assets/app.min.js`, both `fetchpriority="high"`, and nothing else — `app.js`
fetches `data/catalog.js` itself once the shell is labelled, and
`data/notes.js` when the Забелешки tab is first opened.

## The boot

The shell is labelled in two phases, because the strings and the catalogue do
not arrive together. Every visible string comes from `assets/i18n.js` and is
written by `renderStatic()`, so a shell painted before `app.js` runs is an
*empty* shell — four blank tabs, an unlabelled toolbar, no header text — and it
moves when the labels land. On a phone that measured CLS 0.885, which is a
quarter of the Lighthouse score. So the inline script in `index.html`'s head
puts `boot-shell` and `boot-foot` on `<html>`, and those classes hold the shell
(and, separately, the footer) at `visibility: hidden`:

- **phase one**, when `app.min.js` executes: the language, the theme, the
  filters handle, the labels — `deserializeShell()` reads the tab, query and
  sort out of the hash, then `showView()` and `renderStatic()`. Then
  `boot-shell` comes off, and *that* paint is the reader's first look
  at the page: right view, right labels, nothing left to move.
- **phase two**, once the catalogue has arrived: `adoptData()`, the full
  `deserialize()`, the event handlers, and the table. `boot-foot` comes off
  last, because on a phone the footer sits where 431 rows are about to arrive
  and a footer painted first moves thirty thousand pixels when they do.

Two things follow. The labels cannot be in the HTML — that is what `i18n.js`
is for — so the shell is *held back* rather than reserved: a `min-height` per
breakpoint would be a guess that goes stale with the translations, and a shell
that shrinks when the text lands shifts just as badly as one that grows. And
the timer in that inline script is the way out if the app never runs: it checks
`window.SHPATO_STARTED`, which `app.js` sets first thing, so it stands aside
for a slow boot and only reveals the shell for a broken one. `#result-meta:empty`
carries a reserved line for the same reason — it is what is left of the
movement once the shell is stable, the count landing on a line the table sits
under.

Measured with Lighthouse 10 mobile against a gzipped local copy of the repo
(GitHub Pages serves gzip; a plain `python3 -m http.server` does not, and
measuring against it is measuring the dev server): **0.99 performance**, TBT
50 ms, CLS 0.02, FCP 1.5 s, LCP 1.9 s. The last hundredth is the typeface: the
two subsets are 42 KB discovered through the render-blocking stylesheet, and
Lighthouse's simulator chains them behind it even though `font-display: swap`
means the paint does not wait for them. Moving them out of that stylesheet
measures 1.00 and makes the page worse — the reader sees the fallback and the
typeface pops in — so they stay where they are. Do not chase that point by
deferring the fonts.

## Minification

`tools/build.py` ends by calling `tools/minify.py`, which writes
`assets/styles.min.css`, `assets/i18n.min.js`, `assets/app.min.js` and
`assets/doc.min.js`; `index.html` loads the first three and `dela.html` the
stylesheet and the last. They are **generated and committed**, like `data/*`,
and the build stays reproducible: `git diff --exit-code assets/` after a build
must be silent.

The minifier is dependency-free and deliberately conservative.

- CSS: comments and whitespace between rules go, but whitespace **inside a
  value** is load-bearing and collapses to one space rather than vanishing —
  `linear-gradient(to right, …)` and `calc(1rem + var(--x))` are invalid
  without it. Punctuation is squeezed only at depth 0, so the bodies of
  `@media` blocks keep their inner rules intact.
- JS: comments go and intra-line whitespace collapses, but **newlines stay** —
  no automatic-semicolon-insertion hazard — and nothing is renamed. `app.js` is
  written a statement per line with semicolons, which is what makes that safe.

Verification is not `node --check`. A CSS pass that ate the space in
`linear-gradient(to right, …)` produced CSS that parsed cleanly and that axe
flagged as 18 new contrast failures inside the facet panel. Render the page and
compare it — axe, and the suites in `/tmp/opencode/harness` — before committing
a minifier change.

`tools/cover.html` and `tools/favicon.html` link `../assets/styles.css` and
keep the unminified sheet: they are render targets, not pages.

## Data workflow

`sources/*.csv` are the input. `data/*` is **generated and committed** — never
edit it by hand. To fix data:

1. edit the CSV (this is expected; "untouched" below means the *build* does not
   rewrite them, not that they are frozen),
2. run `python3 tools/build.py`,
3. commit the CSV **and** the regenerated `data/*` together.

The same run writes `dela.html`, the static catalogue page, from the records
rather than from the payload, so the two cannot disagree. It is generated and
committed too; see "The static catalogue page".

The CSVs are CRLF, like the monograph exports they came from. A tool that
rewrites one has to write CRLF as well, or the commit is the whole file.

The build is deliberately reproducible: `python3 tools/build.py && git diff
--exit-code data/` must be silent. That is why there is no build timestamp in
the payload. If your change makes that command dirty, something in the build is
non-deterministic.

`count_warnings()` must run after `mark_duplicates()`, which appends flags.

The `expected` dict at the bottom of `build.py` is a guard, not truth: it warns
on stderr when the per-category counts move. Update it only when the move is
intentional.

`sources/removals.csv` (`file,line,title,performer,signature,same_as`) lists rows
the source holds twice and the catalogue therefore carries once. `drop_rows()`
runs **after** the ids are handed out: a drop made earlier would shift every
later id in that category and send `sources/youtube.csv` at the wrong works.
`line` is the weakest thing to key a deletion on, so the other three columns are
guards — checked against the record and reported, never applied, when they
disagree.

A row goes only when the catalogue is known to carry the same work elsewhere, and
there are two ways to know it. Blank `same_as` means the pair is an exact
duplicate and the twin is found by its `duplicate_key()`; a `same_as` value names
the work that is kept, and the pointer has to resolve to exactly one record in
the same category with that title. The pointer exists because one pair is not an
exact duplicate and only a person can say so: the vocal volume lists «Играј и пеј
калипсо» bare on line 21 and «Калипсо» with Љупка Апостолова, its timing and its
shelf mark on line 28, and they are one work — the 1958 Jugoton single "Igraj
Kalipso" (music D. Đakonovski, lyrics D. Georgiev), whose one upload is already
on «Калипсо». The catalogue keeps the phonotheque's short title, and the drop is
one `duplicate-dropped` note naming it. A pointer that matches none, or more than
one, is reported and the row kept, because a wrong drop takes a unique record out
of the catalogue with no symptom.

The `Гарача` this list once dropped is no longer in the export we hold, so the
build has nothing left to remove there and the list carries the calypso pair
alone. Deleting a row from a source **shifts every later id in that category**,
which is what the generated catalog warns about through the `title` guard in
`sources/youtube.csv`; re-point the map by the same shift rather than by matching
titles, because a category holds more than one work with the same name.

Every normalization must be recorded in the notes pipeline (`textFixes` /
`flags`, with a `SEVERITY` entry) or it is invisible in the Забелешки tab.
Never "fix" a title or name silently. A dropped row is recorded there too, under
`duplicate-dropped`: it has no record left to carry a flag.

The arrangement volumes write `Авторот` in the performer column where the song's
author sang his own piece. That is a pointer, not a name, so the build replaces
it with the composer the same row credits (`performer-author`, after the alias
map, so `Х. Крствески` arrives as `Христо Крстевски`) and says so in Забелешки.
The source keeps the export's wording, as it does for `+++` and the abbreviated
names. Five records carry it.

The broadcasters and their house ensembles are abbreviated too: `ТО` is Танцов
оркестар, `РО` Ревиски оркестар, `ГЗО` Голем забавен оркестар, `ЗО` Забавен
оркестар, `РТС` Радио-телевизија Скопје, `РТ` and `РТВ` Радио-телевизија,
`РТЉ` Радио-телевизија Љубљана, `МРТ` Македонска радио-телевизија, `РС` Радио
Скопје. `expand_ensembles()` spells them out wherever they stand as a word, in
the performer and in the role after `со` (so `соло гитара со ТО на РТС` reads
`соло гитара со Танцов оркестар на Радио-телевизија Скопје`), and records each
substitution under `ensemble-expanded`. It runs *after* `apply_maps()`, so
`Забавен анс. на РС` is a name before `РС` is spelled out, and in a single pass,
so a replacement is never expanded twice. `ЗА` and `ГО` are deliberately left as
written: what they stand for is not established. `РТЉ` was, once the ensemble's
own uploads named it ("Revijski Orkestar Rtv Ljubljana"), and `ГЗО` and `ЗО`
rest on the export spelling them out itself, with the initials exact; that is the
standard for settling any that follow. A spelling-out that changes a `performer`
has to reach `sources/removals.csv` too, whose `performer` column is a guard on
the row it drops — otherwise the drop stops applying and the catalogue grows a
record.

Inside a role the export clips words as well: `сакс` for саксофон, `арр.` for the
Macedonian `ар.`, and a year with its `г` run into it (`сним. 1959г`). Those are
`abbreviation-normalized` fixes in `ABBREVIATIONS`, which runs on the whole
performer cell before the name/role split, so the role is cleaned with the rest.
A name abbreviated to an initial is spelled out only where the catalogue also
carries the full form (`Љ. Димитровска` → Љупка Димитровска, `Б. Ноев` →
Божидар Ноев, both `name-unified`); the ninety-odd credits the monograph gives
only in initials stay as they are.

The two volumes of his own compositions carry no `автор` column at all — their
header is `наслов,изведувач,минути,сигнатура` — so their author cells are empty
not because the value is missing but because the volume *is* the author. That is
a presentation gap, not a data one, so the app fills it: `adoptData()` sets
`composer` on every `vocal`/`instrumental` record that has none (`SELF_AUTHOR`,
which tracks `app.title`'s spelling, Cyrillic in both languages because a name
is data). One fill there, before anything renders, is what keeps the table, the
drawer, the composer facet, sort-by-Автор and both exports reading the same
value; a label in the cell alone would sort and filter as empty and leave
`data/catalog.json` disagreeing with what is downloaded. The same pass appends
the name and its `toLatin()` form to `r.search`, because `build_search()` bakes
that haystack and `matchesQuery()` never reads the fields. The 12 `+++` rows
stay blank: the build blanks that placeholder on purpose and flags it
`composer-placeholder`, which is a different statement from "this volume has no
author column". The drawer's «Ист автор» is suppressed for `SELF_AUTHOR`, whose
list would be every other work in the catalogue rather than a cross-reference —
the same condition as the fill.

## YouTube links

`sources/youtube.csv` (`id,title,video,found,lengthSec,added`) is the link map,
part hand-checked and part machine-filled. `id` is positional (`vocal-0007`), so
`title` is a guard: `attach_videos()` warns when it disagrees with the record,
because a shifted id would otherwise attach a video to the wrong work with no
visible symptom. A value that is not a valid 11-character id (or a pasted
YouTube URL) is dropped with a warning. The field is present on every record,
`null` when unknown.

`added` is the day the link went in (`YYYY-MM-DD`), and it is what the NEW badge
beside a title is derived from: `attach_videos()` sets `isNew` for a row whose
date is on or after `NEW_SINCE`. So adding a link announces it with no second
edit, and moving that one constant forward retires the badges it leaves behind
— the build never reads the clock, because a date it took from "now" would make
the committed payload unreproducible. `tools/youtube-search.py --apply` stamps
its rows with the day it runs, and `--verify`/`--drop`/`--backfill` carry the
column through, so a pass cannot silently un-badge a row. A blank date is never
badged, and a malformed one is reported and read as blank; the date is checked
rather than trusted, because comparing it as a string would otherwise let
`2026-13-45` sort as recent.

The count of badged rows is `meta.new`, which labels the toolbar's "Само ново
(n)" toggle and hides it when it reaches 0 — so a `NEW_SINCE` moved far enough
forward retires the filter along with the badges, with no second edit.

Backfilled from git history: a row's date is the commit that last introduced it,
so a row restored after the audit carries its restore date, not its original
one. `git log -S "<id>," -- sources/youtube.csv` recovers any row's history.

One upload can belong to two records, and that is not a fault to repair. The
monograph is an inventory, so a work the phonotheque holds in two archive units
gets two rows — same title, composer and performer, different shelf marks
(`Сењорита Калипсо` at `АЗ-49/7` and `АЗ-55/19`, `Мојот јуни` at `АЗ-46/4` and
`АЗ-62/11`). Both rows then carry the same link, because it is the same
performance, and `possible-duplicate` marks the pair. `drop_rows()` will refuse
to drop one anyway: the shelf mark is part of `duplicate_key()`. A link that
appears on two *different* titles is the fault — `vocal-0020` had one, a
`search` row on the same upload a hand-checked row already held, and it was
removed rather than kept.

`found` says where a link came from: blank or `human` for one a person checked
(blank is how the first 39 rows read — they predate the column), `search` for
one `tools/youtube-search.py` accepted and nobody confirmed. `lengthSec` is the
upload's own duration. A `search` link becomes an approximate match when its
length is more than `VIDEO_DURATION_TOLERANCE` (5 s) from `durationSec`, or was
never learned: the record gets `videoApprox` and the `video-approximate` flag,
so the drawer says "found automatically, may be a different edition" and shows
the upload's duration with the difference, and Забелешки carries a note under
that rule (severity info) with both durations. The build decides the mark, not
the finder, so the threshold lives in one place. A `human` link is never
marked, whatever its length.

What the finder accepts: a link is the record's own performance. The drawer has
no way to say "different performer", so a candidate is accepted when its title
carries the work's title *and* the catalogue's performer is named on the page —
in the video title, which is where a hand-checked link almost always has it, or
on the uploader's channel, where a "... - Topic" channel carries the artist and
little else (`arrVocal-0223`). Nothing else stands in for it, not the arranger
credited and not a channel a hand-checked link came from, with the one exception
below. The looser rule that allowed both wrote 20 links out of 86 with no
performer anywhere on the page: "Кирчо Поп Лазаров - Сини Очи" on Веле Матевски,
"Христо Крстевски - Пролетно сеќавање" on Нина Спирова, and an 8:39 tribute
montage on Трио Лабиш, accepted on the arranger's name alone. `ROLE_WORDS` is
what stops "ТО на РТС" from matching on "РТС" alone, which is on half the
archive; the city in "Радио-телевизија Скопје" belongs to the institution the
same way, so it goes too.

The trusted channel survives in one place: a performer with no identifying word
at all — an empty cell, or a house ensemble whose name is nothing but role words
("Забавен оркестар", "Оркестар", 19 records) — leaves nothing to check, and a
title on a channel a hand-checked link came from is then all the evidence there
is.

Duration settles nothing either way: "Blagoja Ceslarov - Aranhuez" is 90 s off
the catalogue's timing and is still the right piece, and it is the build, not
the finder, that marks a link whose length disagrees.

The title test is deliberately the part that does **not** get loosened: an
artist-only loosening attaches the wrong *recording* of the right song, a
title-only one attaches a different *song* that shares the name — Serbian "Bez
tebe", Russian "Чувства", Slovakia's Eurovision "Kristina" — and the "found
automatically" mark cannot warn about that. `title_hit()` therefore wants every
significant word of one of the work's names, allowing only for an inflected
ending (`word_in()`). Half the words was not enough: "Тоше Проески — Сонце во
твоите руси коси" matched "Да потонам во твоите коси" on "во твоите коси"
alone, and the word that names the song ("потонам") was the one missing. A title
with a number in it is covered by the same rule, so "Тема бр. 1" cannot match
"Тема бр. 2"; so is a title's negation, which `NEGATIONS` keeps in the words to
match, because "Верувај ми" is not "Не ми верувај". One short word may still be
missing — an uploader writing "Igraj kalipso" for "Играј и пеј калипсо" is not
naming a different song — but only in a title of three words or more, so that
"Мојот дом" is not reduced to "мојот". `compare_word()` folds the transliteration
variants that stand for one letter (ч romanised as "ch" against an uploader's
"č", ќ as "kj" against their "k"): "Молчи" arrives as "molchi" against their
"Molci", "Ќе наминеш" as "kje" against their "Ke", and a whole-title test would
otherwise lose a song to a spelling difference. The same folding is applied to
`ROLE_WORDS`, or the fixed set would never meet a folded page, and `word_close()`
allows the one letter that separates an uploader's spelling from the catalogue's
("А. Сурмеан" against "Армен Сурмејан", "Lupka" against "Љупка") — from six
letters up, where one letter is a spelling and not another name.

A work's title can also name the piece twice — "Осаменост (Молчи една долина)"
is one piece under two names, and an upload carries one of them — so
`title_forms()` keeps the title without its brackets *and* the contents of any
bracket that is not a qualifier, and matches on any of them.
`QUALIFIER_WORDS` is what makes a bracket saying only *how* an edition was made
("(џез верзија)", "(live)") count for nothing: that is how "Ева — За љубов
створени (Џез верзија)" had matched "Ми вети ти (џез верзија)".

Three further guards, each measured against what a pass actually attached
(`--apply` over the first 100 unlinked works attached 36 links, three of them
wrong):

- `plausible_length()` — an upload may be well off the catalogue's timing and
  still be the work, so length never confirms a link, but it cannot be
  arbitrarily longer either: half the length is a clip, and more than
  `PLAUSIBLE_SLACK_SEC` (120 s) over it is a podcast or a whole album. This is
  what refused a 71-minute Croatian podcast for a 3:50 song and a 10:51 concert
  for a 5:36 one.
- A one-word title is a weak identity, so it asks for the performer's surname —
  the last word of the name ("Апостолова", "Мицев"), or an ensemble's own word
  ("Ревиски" in "Ревиски оркестар на Радио-телевизија Љубљана"), with an
  institutional acronym skipped. That is what keeps "Zašto je uspjeh najveća
  iluzija?" by a host called Zoran from becoming the song "Илузија" by Зоран
  Георгиев, while "Lupka Apostolova - Igraj kalipso" still answers for «Калипсо».
  Asking for the whole name instead cost that hand-checked link: "Lupka" is
  "Љупка" a letter away.
  Measured over the 86 links the looser rule wrote, the performer requirement
  refuses 16: 6 name another singer outright, 9 name an orchestra or the
  arranger's own channel where the catalogue credits a soloist, a quartet or a
  different ensemble, and 1 is a title mismatch the older rule already refused
  («Каде си мајко» for «Кај си мајко»).
- `dedupe_picks()` — with 38 titles naming more than one work, one upload can
  pass the test for two of them; a scan keeps it for one work only.

A *candidate's* duration is still never used to confirm anything: the build
alone marks, and only within `VIDEO_DURATION_TOLERANCE`.

The chain runs title+performer, its core, both romanised, the title alone, the
performer alone and title+Шпато, stopping at the first query that yields an
accepted candidate. `--selftest` replays the hand-verified links as unknown,
with each work's own channel left out of the trusted set, and measures the
rule: 50/53 recovered, 45 as the best pick, 77 other candidates accepted. The
looser rule measured 51/53 and 112 others on the same run; requiring the
performer costs one upload and 35 of the candidates that were never this
record's performance. The three misses are an upload titled "Indiana" for
«Индијана», one that names no performer at all («Во спомен на старото
пријателство» for Мики Асановиќ), and arrVocal-0055, where the rule does find
the work — nine uploads of Tomislav Manic singing it — but not the one a person
had picked. Run it before changing the rule, and read the measured numbers
rather than guessing.

Only `--apply` writes: new rows go in with `found=search`, and a row that
already has a video is never overwritten or re-searched. The finder reuses
`to_latin()` from `build.py` rather than growing a third transliteration.

Where the pass over the 361 works that were still unlinked left the catalogue:
127 of 431 works carry a link, 73 of them machine-found — vocal 34/73,
instrumental 9/55, arrThemes 2/43, arrVocal 82/260 — with the rest of the
catalogue offered as a YouTube search from the drawer instead. A machine-found
link that is not within `VIDEO_DURATION_TOLERANCE` of the catalogue's timing is
marked, so the reader is told. The five links an earlier re-audit refused are
not there, and neither are 13 of the 16 the performer rule refused once it was
made strict: two of those works were re-linked to an upload that does name the
performer, and `instrumental-0050` was put back after a second look, because its
upload names the record's own orchestra and no contradicting soloist — the best
evidence there is, where the alternative is none. It is marked `found=human`,
since a person made that call, so `--verify` will not take it out again.

When the rule changes, the rows a pass already wrote down do not have to be
searched for again: `--verify` asks YouTube for each machine-found upload's own
title and channel, runs `accept()` over the length the row recorded, and reports
which rows the rule still stands behind; `--drop` removes the ones it does not.
Hand-checked rows are never touched, and a row whose upload cannot be asked
about is kept and reported — a network answer is not a verdict. That is how the
first pass's three bad links came out (a 71-minute podcast, a concert, and a
title that shared only its bracketed words) while its 32 good ones stayed, which
is cheaper and safer than discarding the pass and searching again.

An empty results page is how YouTube answers a query it does not want to answer
as well as one it has no match for, and a silent zero is indistinguishable from
"not on YouTube". `search_candidates()` therefore asks a second time, more
slowly, before it believes a query found nothing, and `--selftest` gives a work
that yields nothing at all one more go before calling it a miss.

YouTube will not play an embed on a page with no origin: Chrome sends no
referrer for `file://`, and the player answers with "configuration error 153"
for every embed host, `referrerpolicy` and `origin` parameter combination
tried. `file://` support is a hard requirement here, so `CAN_EMBED` is false
there and the play button opens the video on YouTube in a new tab instead of
mounting a player that can only fail. Do not "simplify" that branch away.

## The About tab

`#view-about` is static prose. The shell carries only the markup and the
`data-i18n` hooks; every sentence lives in `assets/i18n.js` under `about.*` in
both languages, as everywhere else.

The facts list is a spanning item of `.about`, not a sibling that follows it,
so its right edge lands under the photograph's at every width where the two
columns exist. A `max-width` on the card cannot do that: `ch` resolves on the
element it is written on, and `.facts` is `.9rem`, so the cap would come up
short. Leave it in the grid.

Every biographical claim there is backed by one of the three references linked
at the foot of the tab (Dimitrov's monograph, Grove Music Online, the FMU
yearbook). Do not add facts from memory: the sources do not agree in places, so
the tab states what they collectively support.

- The first Macedonian jazz composition is given as "На игранка" (1948), as the
  monograph and the press have it, not Wikipedia's "Тема I" (1947).
- Both documented wives are named: Катица Ѓаконовска (the monograph credits her
  as the singer on four of the arrangements, which is how she also appears in
  the catalogue) and Марија Ѓаконовска (his last piece, "Марија" from 1986, is
  dedicated to her). Do not collapse them into a single wife, and do not say
  which was Martin's mother — the German sources name Катица, the Macedonian
  ones Марија.
- The birth date is 11 March 1931 (Makedonska Enciklopedija, mk.wikipedia); the
  8 July 1931 that SOKOM's member biography prints is the outlier. The opus
  figure is "над 3.000 аранжмани", against 5,000 in German Wikipedia and
  "неколку стотини" in SOKOM's own text.
- The photograph is a Slobodna Evropa (RFE/RL) frame of him conducting a big
  band, taken from slobodnaevropa.mk/a/3537129.html. It is RFE/RL's, so the
  caption carries the credit (`about.credit`); keep the credit with the image.

The photograph also carries `about.photoAlt`, set through `data-i18n-alt` like
the rest of the strings, so a screen reader and an image search get a
description of the scene the caption credits.

`index.html` carries a JSON-LD `Person`/`WebSite`/`CollectionPage` block for
search engines. It restates these facts — name, dates, places, roles, the
photograph, and the references as `sameAs` — and nothing generates it, so it has
to move with `about.*` whenever one of them changes. Its URLs are absolute, like
the OG tags, and follow the domain with them. It deliberately holds no counts:
the app owns those, and a number written into the HTML would go stale without
anything noticing.

## The static catalogue page

`dela.html` is generated by `tools/build.py` and committed like `data/*`. The
app is a shell: the works arrive only after `app.js` fetches `data/catalog.js`
and builds the table, so a crawler that runs no scripts reads a shell. The page
is the same catalogue as one plain document — one `<h1>`, one `<h2>` and one
table per category, the works title-sorted inside each — so the data is in the
HTML that is served. It exists for the crawlers that do not wait for a fetch.

It is built from the records, not from the payload, so the counts, titles,
performers, composers, durations and signatures cannot drift from the table. Two
things are added at generation time, both of which the app does at runtime for
the same reason:

- the author column of the vocal and instrumental volumes, which carry no author
  column at all, is filled with the subject's name as `adoptData()` fills it;
- the order is `collate_key()`, a port of `compareText()`/`collationRank()` from
  `app.js`. The two are the same Macedonian alphabet and have to stay in step,
  like `toLatin`/`to_latin`.

Its Macedonian prose is the one place the rule that every string comes from
`assets/i18n.js` cannot hold — the page must carry text with no script to put it
there. The labels live in `PAGE_TEXT` at the top of the page generator and mirror
the mk values of `app.title`, `app.catalogTitle`, `app.subtitle`, `app.credit`,
`footer.allWorks`, `theme.*`, `share.*`, `a11y.skip`, `cat.*`, `col.*`,
`privacy.link` and `common.none`; change both together. Its icons are the same
rule applied to markup: `PAGE_THEME_ICONS` and `PAGE_SHARE_ICONS` are the paths
`index.html` carries inline, because the page has no `app.js` to draw them.

The page carries structured data of its own: a two-level `BreadcrumbList` (the
app, then this list) and a `CollectionPage` for this address, `isPartOf` the
app's `#website` and `about` its `#person`. Both entities are referenced by
`@id` rather than restated, so the person's dates, places and references have
one definition, in `index.html`, and this page cannot drift from them. Nothing
in the block counts anything, and there is no per-work `ItemList`: the rows are
the data, and 431 items restated in a second vocabulary would only be 40 KB of
HTML saying what the tables already say. The breadcrumb's first crumb is
`PAGE_TEXT["breadcrumbHome"]`, which is `app.catalogTitle`; its last carries no
`item`, since it is the page it is on.

The page links `assets/styles.min.css` and carries two scripts that run. The
first is the theme line from `index.html`, without the boot classes, so a reader
who chose the dark theme in the app does not get a white flash here. The second
is `assets/doc.min.js`, and it exists because the shell is the app's and the app's
controls work: it makes the theme switch write the same
`localStorage["shpato-theme"]`, fills the four share intents from this page's
canonical address, and sets `data-pan` on each `.table-frame` so the pan cue
follows the scroll position, as `app.js` does for the app's table. It carries no
analytics — Search Console is what measures it — and makes no third-party
request; the other hosts in the page are the credit link and the share intents'
`href`s. It is its own canonical URL (`/dela.html`) and stays self-canonical:
the app keeps the root it is shared by, and canonicalising either to the other
would drop one of them from the index. The app links it from the footer, which is
the crawl path. Its links back name `index.html` rather than `./`: the page is
read from disk too, where `./` is a directory listing; on the web the app's
canonical folds that URL into the root.

The header and the footer are the app's, so a reader who follows a link between
the two does not arrive somewhere that looks like another site. The header has
the same brand, the same full subtitle and the app's theme switch. The footer has
the app's credit line, the four share intents and the same `space-between` to
`center` wrap at 620px; `Сите дела на Шпато` is where the reader already is, so it is
a span rather than a link to itself. Both pages draw those from the same CSS.

The tab strip is deliberately absent. It is not navigation on this page: it would
be a current tab for a view the reader is already in, beside three that leave for
another document. The page's own `Содржина` list is what moves a reader around
it, and the brand and the `Отвори го интерактивниот каталог` button are how they
reach the app and its other views. A strip here would also be sticky over a
38,000px document, which is a scroll aid the TOC already does better.

The `Содржина` entries are the app's own `.btn` pills, each carrying its
category's dot — `data-cat` on the link, so the four facet colours are the four
dot colours — and its count inside the link rather than beside it, and each
section heading repeats the count as the same small chip. The pill is
`display: inline-block` rather than a flex row on purpose: the longest label is
two lines at 390px, and a flex count would sit centred against that pair at the
pill's right edge instead of following its last word.

There is deliberately no language switch. The page and every work in it are
Macedonian, and the app's switch changes only its own labels; a switch here would
have to make the whole document bilingual to be honest about what it did. The
theme switch is different: it is one stored preference that both pages share.

One thing the app gets for free needs a line here: the table card cannot scroll
vertically (its box is the whole table), so
`.catalog-doc .table-wrap { overscroll-behavior-y: auto }` keeps a drag over it
scrolling the page; leaving the base `contain` would swallow the gesture over
most of a phone screen.

The rows are not links: there is no per-work URL yet, and the title cell is where
one goes when there is. The tables are the app's, minus the pointer and the hover,
because a row here does nothing.

## Analytics and the privacy notice

`index.html` carries the Matomo tracker (`analytics.gocemitevski.com`, site `3`)
in the `<head>`, loaded `async` and only when `location.protocol` is `http:` or
`https:`. The guard is not decoration: the app must keep working from `file://`,
and on `file://` the absolute analytics URL would track a local read of the
catalogue. There is no `<noscript>` pixel — with scripting off the shell is
visible but empty (no labels, no table) and there is no catalogue to read — so
a no-JS reader is not counted.

The tracking is **cookieless**, in two halves. The instance enforces it (Privacy
→ Anonymize data → *Force tracking without cookies*), which Matomo bakes into
the served `matomo.js`; and the page queues `disableCookies` before
`trackPageView`, so a change on either side alone cannot bring an analytics
cookie back. `discardHashTag` is queued for the same reason: the catalogue keeps
its state, search text included, in the fragment, and Matomo would otherwise
record it as part of the page URL. Both must stay before `trackPageView`, which
is the first call that reads them. `discardHashTag` is deprecated in Matomo 5
but still honoured by the served tracker; if it is removed, use `setCustomUrl`
before `trackPageView`. `enableLinkTracking` is on, so outbound clicks are
counted too; the privacy notice says so.

`assets/app.js` no longer loads or gates anything. It carries
`clearLegacyAnalytics()` instead, run once at boot: it removes the old
`localStorage["shpato-consent"]` and deletes the old property cookie
`_ga_G-Z2QYKW1QNC` on the host and on the registrable domain, because the tag
took the registrable one when it could. The generic `_ga` and `_gid` cookies are
left alone: `www.gocemitevski.com` still uses Google Analytics on the same
registrable domain, and those cookies are shared. That is what makes "the
catalogue sets no analytics cookies" true for a reader who visited before the
change, without breaking the neighbouring property. When www moves
off Google Analytics, the shared cookies can be cleaned up too.

Do not add the Matomo Tag Manager container alongside this tracker. The container
already holds a Matomo tag (site 3, PageView, link tracking) and bundles its own
copy of the tracker, so the pair would create two trackers and two pageviews.
If Tag Manager is ever wanted for other tags, the Matomo tag inside it has to be
disabled first, or the tracker removed from `index.html`.

`#view-privacy` is the notice, the one view with no tab of its own: the strip is
sized for four, so it is reached from the footer's `#privacy-link`. `openPrivacy()`
calls `setTab("privacy")` and then puts focus on its heading, since no tab exists
to announce the switch, and its `role` is `region` rather than `tabpanel` for the
same reason: nothing controls it. `setTab` keeps the first tab in the roving
tabindex when the active view has no tab of its own, or the whole strip would
drop out of the tab order; `t("tab.privacy")` exists for the document title
alone.

Every sentence there is `privacy.*` prose in both languages, like `about.*`, and
it deliberately carries no "last updated" date: that date would have to be
hand-edited at every change and would go stale without anything noticing, the
same reason the build payload has no timestamp. What it says is what is true
today — the notice states the purpose and the right to object, the raw log is
promised gone after 180 days, visits are measured without analytics cookies or a
persistent identifier, nothing is sent to Google for analytics, the player is
`youtube-nocookie.com` and fetches nothing until a recording is pressed, and the
two browser settings the page stores (theme and language) are functional and
never transmitted. The notice deliberately leaves the legal basis out; if one is
added, update both languages and this paragraph. The 180 days is a promise, not a
default: it holds only while Matomo's *delete old raw data* is enabled at 180, so
change the notice if that setting moves. If any of the rest changes, the notice
has to change with it.

## The shell

`index.html` is an app shell, not a document: `body.app` is a grid pinned to
`100dvh` with `overflow: hidden`, and the page itself never scrolls. What
scrolls is `main`, and the panes inside the visible view. The body class is what
keeps all of this off `tools/cover.html` and `tools/favicon.html`, which link the
same stylesheet and must keep their own bodies.

The viewport carries `interactive-widget=resizes-content` for the opposite
reason: with a keyboard up, a shell pinned to `dvh` would otherwise keep its
full height and leave the results behind the keyboard. Resizing the layout
viewport shrinks the shell with it. Browsers that do not know the key ignore it.

- `#view-catalog` and `#view-notes` fill their pane (`height: 100%`; a grid whose
  middle row is `minmax(0, 1fr)`) instead of growing the page, so their toolbars
  stay put and the tables scroll inside their own cards. That is also what
  finally gives `.catalog-table thead th { position: sticky; top: 0 }` something
  to stick to: while `.table-wrap` was `overflow-x: auto` only, its `overflow-y`
  still computed to `auto`, so the card was already a scroll container that
  never scrolled vertically. Bound the table and the sticky header works for
  free.
- The `body.app` column is `minmax(0, 1fr)` on purpose. Left implicit, the column
  sizes to content and the tab strip's min-content is wider than a phone: the
  shell grows past the viewport and the last tab ends up behind the clipped
  edge, with nothing left to scroll it back. `#view-catalog` and `#view-notes`
  pin their column the same way for the same reason, and it matters most for
  the notes toolbar: a `<select>` is as wide as its longest `<option>`, the
  longest rule name is 377px at the default font size, and an implicit column
  used to let that widen the whole view — title and intro with it — past the
  pane, leaving `main` with a horizontal scrollbar. `.field` carries its own
  `min-width: 0` for the matching flex-item reason; the select then stretches to
  whatever line it lands on and the rule name ellipsizes.
- `<footer>` is the shell's last grid row, not the end of the pane. The pane
  therefore never scrolls to reach it, and the catalogue never grows a second
  scrollbar beside the table's own. It is kept short — `.75rem` of vertical
  padding, so about 52px at a desktop width — because every pixel of it is a
  pixel the catalogue cannot show, and `main` keeps `1.25rem` of bottom padding
  of its own so that the last card's border and the footer's rule do not draw
  the same line. The credit sits at its left — carrying the two doors that are
  not tabs, the full list (`dela.html`) and the privacy notice
  (`#privacy-link`), in the footer's own neutral colour and with `.5rem` in
  front of each, half the `1rem` that separates the two groups — and a group of
  four sharing links at its right: 1.5rem targets, the smallest that still
  clears the 24px minimum, held apart by `justify-content: space-between`. The
  634px block turns that into `center`, so on a phone the pair sits centred, and
  each of them on its own line once they wrap. The doors moved the wrap: the
  credit and the share group need 568px of inner width together, so the pair
  fits one row from 618px of window while the scrollbar floats over the page and
  from 634px once it takes its 15px — measured, not summed, and the static page
  is the one that carries that scrollbar, because a 38,000px document always
  scrolls where the pinned shell never does. That band is why the centring stops
  at 634px rather than 620px; at 620px the share group would sit at the start of
  a line of its own in it, and on the static page the wrapped pair stays centred
  from 621 to 633. It costs the catalogue
  nothing, because everything below 620px is already standing down, where a
  second row is a second row of the page.
- `.filters` and `.table-wrap` set `overscroll-behavior: contain`: a wheel that
  reaches the end of a facet list or of the table stops there instead of
  carrying on into the shell. Each `.table-wrap` sits in a `.table-frame`, and
  the frame draws the cue that the card can be panned sideways — on a phone the
  table is 706px inside a 361px card and nothing else on screen says so. It
  cannot be a layer of the card's own background: those lie under the card's
  children, and a `th` has to stay opaque or rows show through the sticky band,
  so a scroller painting into its own background can never shade the header row.
  The two gradients are instead two empty `.pan-cue` elements of the frame — a
  layer above the card, pinned to the frame rather than to the content, which
  shades the header row too — and one layer per side is what lets one show while
  the other is hidden. They are elements rather than the frame's
  `::before`/`::after` because axe cannot settle the contrast of anything an
  ancestor's pseudo-element might paint over: as elements the catalogue reports
  no undecided contrast, as pseudos it flags every cell in the table. A layer
  above the card cannot see the scroll position, so `app.js` puts which sides
  still have table left on `data-pan` and the stylesheet shows the gradients; the
  pair cross-fades when the card is panned to an end. The frame is also what
  gives the card its height: it is the `.results`/`#view-notes` grid item, and
  the card fills it with `flex: 1`.
  `.table-wrap` is `position: relative` for a reason worth keeping: an
  absolutely positioned descendant whose containing block is outside a scroll
  container is not clipped by it, and every row holds a 1x1 `.visually-hidden`
  span whose static position, thousands of pixels down the table, then becomes
  scrollable overflow that reaches the shell — a pane pinned to `100dvh` gets a
  scrollbar of its own and the positional check below fails. Shade and fade are
  both 2rem wide and `--shadow-edge` is weak on purpose: the cue is meant to
  read as a wash rather than as a band with an edge, so widening it lengthens
  the wash rather than deepening it. Print drops the two gradients, because
  paper does not pan, and reduced motion drops their cross-fade.
- The empty message ("no works found", "no notes") is a child of `.table-wrap`,
  not a row of `.results`/`#view-notes`: as a grid row it was laid out past the
  card's bottom edge, at the foot of the pane, where it read as a caption on the
  pane rather than on the card. Inside the scroller it stands in the card where
  the rows would begin, under the header row — and a block there is only as wide
  as the card's *visible* width even though the table overflows it, so on a
  phone the line centres where the reader is looking rather than in the table's
  overflow. It is `position: sticky; left: 0` because that header row can still
  be panned. A card with no rows still draws its header row, so the pan cue
  stays on while the header overflows.
- From 1024px up the facet panel is a permanent left pane
  (`clamp(260px, 32vw, 500px)`). Below that it is a disclosure above the table,
  opened from a handle in the toolbar (`#filters-toggle`, the export menu's
  `aria-expanded` + `hidden` idiom: no modal, no focus trap). Closed, the table
  keeps the whole pane; open, `.layout:has(.filters:not([hidden]))` splits it
  45/55 so neither can push the other out of sight. The panel takes the smaller
  share because it scrolls inside its own half and the table does not. The
  collection facet carries a `.facet-note` above its list: its values are MRTV
  phonotheque shelf marks, and the monograph the catalogue copies them from
  prints them with no key, so the note says so rather than guessing at an
  expansion.
- The width is the script's business too: `matchMedia("(min-width: 1024px)")`
  hands the panel over — wide, it is simply there and the handle is hidden;
  narrow, the handle shows and the panel starts closed. That width is written out
  in the stylesheet and in `app.js` by hand, so changing one means changing the
  other.
- Below 620px the mark takes `order: 1` and keeps its 56px, so the brand reads
  text first and portrait after, and the header centres: the brand on its own
  row, the theme and language toggles on the next. The search gives up its
  320px basis there, so the handle shares its row instead of costing a row of its
  own. The four tabs need 443px at the default gap and size and a phone offers
  361 of them, so the strip tightens too — `.78rem` labels that `flex-grow` to
  share the row, at a `1.25rem` gap. That gap needs 386px of strip to sit in, so
  from 385px down the labels drop to `.7rem` and the gaps to `.4rem`, which need
  about 315px and fit even a 320px phone (or a window at 200% zoom). The last tab
  used to hang off the edge: swipeable, but with nothing showing that it was. The
  strip's own padding stays where `main`'s is, so the first tab still lines up
  with the table. The subtitle is *not* dropped there: it wraps to two lines and
  the header costs the pane 23px for it, which is cheaper than the empty band it
  looks like without one. `text-wrap: balance` keeps the two lines from ending on
  "МРТВ".
- The shell stands down in two windows. Below 600px of *viewport height*
  (`@media (max-height: 600px)`) there is no room for the header, the toolbar
  and a table worth reading. Below 620px of *width* — a phone — the shell costs
  more than it gives: at 393x851 the pinned chrome took 356px of 851 and left the
  table 380px, about seven rows, and with no document to scroll the browser's
  address bar could never collapse to give any of it back. Stood down, the table
  has the whole page and the tab bar still sticks to the top (the document is the
  scrollport now); what is given up is the sticky column header: the card still
  pans sideways, so `overflow: auto` keeps it a scroll container, and a sticky
  `thead` resolves against that scrollport rather than the page's, and that
  scrollport never moves vertically — so the header travels with the document
  and the five sort buttons live at the head of the table. The print block
  undoes the shell for the same kind of reason: a printer wants the whole
  catalogue, not one clipped viewport of a scroll pane.
- Stood down, `.table-wrap` and `.filters` release their vertical
  `overscroll-behavior: contain` (`overscroll-behavior-y: auto`, scoped to
  `body.app` because the base rule is a shorthand declared later in the file and
  would otherwise reset the axis). The card cannot scroll vertically there — its
  box is the whole table — so without the release a drag over it, which is most
  of a phone screen, scrolls nothing at all. The horizontal containment stays:
  that axis still pans the table.
- `setTab()` sends both scrolls back to the top: `main.scrollTop = 0` for the
  pinned shell, and `window.scrollTo(0, 0)` for when it has stood down and the
  document is the scroller. Without both, a tab opens part-way down wherever the
  previous one was left — on a phone in landscape that used to mean the About
  heading landing 206px above the viewport. `<html>` scrolls smoothly, so the
  jump is made with `scroll-behavior` temporarily `auto`. It runs on every tab
  click, not only on a change, which makes the active tab a return-to-top too:
  on a phone that is the reader's way back to the sort buttons at the head of
  the table, since the header itself cannot pin there (see the stand-down note
  above) — an early return for the tab already selected would take that gesture
  away.
- `body.player-open` reserves the player's room inside `.table-wrap` and `.view`,
  never by padding `main`: padding `main` would make the shell scroll to reveal
  nothing but itself.

The check that matters when touching any of this is positional: with the shell up,
scroll the table to its end and the header, the tab bar, the facet sidebar and the
footer must not have moved, and the pane must not have gained a scrollbar of its
own.

## Conventions

- **All UI text is bilingual.** Adding a key means adding it to *both* `mk` and
  `en` in `assets/i18n.js`. `t()` falls back to English silently, so a missing
  Macedonian key will not throw — it will just ship English. Keys are currently
  at parity (182 each). The one exception is `dela.html`, whose text has to be
  in the document with no script to put it there; see "The static catalogue
  page".
- **Capitalisation lives in the strings, not in CSS.** A `<select>`'s
  `<option>` does not inherit `text-transform`, so a CSS-capitalised label looks
  right in the table and wrong in a dropdown. Capitalise in `i18n.js`.
- All user-visible strings go through `data-i18n` / `t()`; no hard-coded prose
  in `index.html` or `app.js`.
- The branded categories are driven by a single `data-cat` attribute that
  resolves to the inheritable `--cat` / `--cat-soft` custom properties. Don't
  special-case a category in JS.
- A catalogue row's title cell is a flex line (`.cell-title-inner`), because
  the play icon and the title must not be able to break apart, and the icon's
  baseline is the bottom edge of its `<svg>` rather than its text. Returning
  that cell to plain inline flow strands the icon above any title wide enough
  to fill the column. Its items share a **baseline**, so the NEW and warning
  badges sit on the title text's own baseline — on a phone, where the title
  can wrap to three lines, that is the first line's, which is where the eye
  reads the name. The play button has no text of its own, so its baseline is
  its bottom edge, and that is what places the circle. This replaced a
  `flex-start` line with a `calc((1lh - 1.3rem) / 2)` drop on the button, which
  put the icon on the first line but left the badges centred on the whole
  block; both the drop and a centring `align-items` fight the baseline and
  should not come back alongside it. `flex-shrink: 0` on the button is not
  what keeps it round — nothing in a table cell shrinks it. The circle's hit
  area is bigger than the circle: a pseudo-element takes it to 40x45px, which
  stays inside the row's top and bottom (the cell's `.85rem` of vertical
  padding is the room; measured at a 390px width it clears the top edge by
  2.5px) and 1px short of the title button 8px to its right, so a thumb
  reaches neither the row above nor the title beside it.
- `[hidden] { display: none !important }` is the only hide mechanism. Use the
  `hidden` property/attribute, not classes.
- `* { box-sizing: border-box }` is global, so a fixed `width` includes padding.
- Theme is the `data-theme` attribute on `<html>` plus
  `localStorage["shpato-theme"]`, with an inline anti-flash script in the
  `<head>` resolving the OS preference. That script must stay inline and before
  the stylesheet. Language is `localStorage["shpato-lang"]`.
- `--theme-color` is mirrored into `<meta name="theme-color">` by
  `syncThemeColor()`; add new tokens to `:root` and both theme blocks.
- Text is pinned with `text-size-adjust: 100%`: iOS inflates it when a rotation
  widens the viewport, and every size here is already meant. A form control is
  kept at 16px or more wherever the pointer is coarse, because iOS Safari zooms
  the page when it focuses one that is smaller — the rule `<select>` inherits
  the field's `.78rem` and would otherwise zoom the notes tab.
- App state is serialised into the location hash (`#tab=…&q=…`) with
  `history.replaceState`, which works on `file://`.
- The brand links to `./`, because the root is the URL the app is shared by. On
  disk that is the directory listing, and a static href cannot be both, so the
  boot re-points it at `index.html` when `location.protocol` is `file:` — the
  same branch, and the same reason, as `CAN_EMBED`.
- The drawer is a modal: `setPageInert()` marks every `body > *` except
  `#drawer` and `#player` inert, and focus returns to the row that opened it.
- There is exactly one `<iframe>` in the app, in `#player-frame`, created on
  demand and removed by `stopPlayer()`. Nothing is embedded on load, and
  removing the element (not hiding it) is what stops the audio. `#player`
  outranks the drawer in `z-index` and steps clear of it above 900px, so a work
  keeps playing, and stays controllable, with the details open.
- `state.onlyVideo` is dropped from a deep link when `meta.videos` is 0, and the
  checkbox is hidden then, so a stale link cannot land on an empty table. The
  same guard covers `state.onlyNew` against `meta.new`, the count of badged rows:
  the toggle is hidden when it is 0, which is also what a moved `NEW_SINCE`
  eventually does. The two toggles are one item of the toolbar (`.checks`), so
  they wrap as a pair instead of one at a time, and the pair is hidden when
  neither has anything to filter.
- Exact duplicates are collapsed at build time, not hidden in the app: the
  catalogue carries one row per item and Забелешки says which row of the source
  was left out and which one stayed (`Нормализирано` names the surviving work
  rather than its id). There is no "show duplicates" control, and nothing in the
  app filters on `duplicateOf` any more. The note for a dropped row names a
  record that is not in the catalogue, so `renderNotes()` gives that row
  `no-record` and a plain title instead of a button that would open nothing.
- The notes payload is fetched the first time the tab is opened, so
  `renderNotes()` has a state for "not here yet": it says `notes.loading` in the
  empty line and calls `loadNotes()`. Everything else in the tab reads `NOTES`,
  so `refreshRuleSelect()` and `severityCounts()` are written to be called
  before it arrives — they no-op or return zeros rather than throwing. A notes
  deep link takes the same path, which is why `boot-foot` is not cleared until
  that payload has rendered.
- The four footer sharing links are share *intents*, not profile links: what is
  passed on is the catalogue. `renderShareLinks()` builds their hrefs from
  `<link rel="canonical">` rather than `location.href`, so they still name the
  site when the page was opened from disk, where a `file:` URL would mean
  nothing to whoever received it. The labels come from `share.*`; the glyphs are
  inline Simple Icons paths (CC0).
- Transliteration exists twice on purpose: `toLatin()` in `app.js` normalises
  the *query*, `to_latin()` in `build.py` bakes the *index* (`rec.search`, which
  is built at build time). Change one and check the other, or search breaks.
- Sorting is `compareText()` in `app.js`, not `localeCompare()`. Chrome's ICU
  build here has no `mk`: `supportedLocalesOf(["mk"])` is empty and `"mk"`
  silently resolves to `en-US`, so it puts Latin before Cyrillic and reads
  Ѓ Ќ Љ Њ Џ Ѕ as plain Cyrillic, while Firefox applies the real alphabet — the
  two browsers opened the catalogue on different works. The comparator is the
  Macedonian alphabet in order, then Latin, with punctuation and digits ahead;
  it is the reason the table and the facet lists agree everywhere.
- Commit messages are imperative mood, sentence case, no prefix.

## Accessibility

The bar is **zero axe-core violations** in both themes, on all four tabs, with
the drawer open, the export menu open and the player open. Re-check it after any
markup change. axe's `incomplete` items on `#export-btn`, the scrollable facet
panel and one-character count chips are pre-existing false positives, not
regressions. `dela.html` is held to the same bar: both themes, with a table
panned to an end so the cue is showing.

Focus order is keyboard-complete; the catalogue table's row buttons alone are
431 tab stops, plus one more for each of the 39 play buttons, so avoid adding
anything focusable per row without thinking about it.

`prefers-reduced-motion` is honoured for the drawer's slide-in, the player's
slide-up and the stats bars. That block sits at the very end of the stylesheet
on purpose: the animations are declared per component, so a copy placed with
any one of them would be outranked by the others declared below it.

## Assets

`tools/cover.html` and `tools/favicon.html` are standalone pages that link
`../assets/styles.css` and are never loaded by the app. Each carries the exact
headless-Chrome command that regenerates its PNG in a header comment; use it
rather than re-deriving the geometry.

The cover must match `.brand-mark`: the portrait is never cropped or scaled
(Chrome clips a rounded `overflow: hidden` box to the *border* box, so a scaled
child paints over the accent ring), and it must show the bare domain
`shpato.gocemitevski.com`.

There are two brand marks, on purpose. `…-Icon.webp` is 512px and belongs to
the two render targets above; `…-Icon-168.webp` is the 56px mark of the header
at 3x, which is all any screen resolves, and is 14 KB smaller. index.html
loads the small one — do not "simplify" that back to the original.

The About photograph carries `loading="lazy"`: its tab is hidden until it is
opened, so it is 170 KB nobody has asked for yet, and on a phone it competed
for the bandwidth that decides first paint.

## Deployment

GitHub Pages via `CNAME` (`shpato.gocemitevski.com`). Pushing `master`
publishes the site. `index.html` carries real OG/Twitter tags and the Matomo
tracker described above; keep the canonical and absolute image URLs in step with
the domain if either changes.

Pages serves `index.html` at both `/` and `/index.html` with no redirect, so
there are two URLs for one document. The canonical names the root, and
`robots.txt` disallows nothing at all. A rule naming the index document reads as
"the root is blocked" to a fetcher that normalises a directory URL into it —
LinkedIn's Post Inspector refused to scrape `https://shpato.gocemitevski.com/`
over exactly that line — and a disallowed URL cannot be seen to canonicalise
anywhere, so the pair is the canonical's to reconcile. The paths that are not
pages (`sources/`, `tools/`, `AGENTS.md`, `README.md`) are left alone for the
same kind of reason: nothing links them, so no crawler reaches them anyway, and a
rule is one more thing to mis-read. `assets/` and `data/` are absent for the
opposite reason — Google fetches them to render the page. `sitemap.xml` lists the
two documents: the root and `dela.html`. The tabs and the search live in the
fragment, and a fragment is not a page. The two `tools/*.html` render targets are
published like everything else, so each carries `<meta name="robots"
content="noindex">`; they are not pages and want no canonical.
