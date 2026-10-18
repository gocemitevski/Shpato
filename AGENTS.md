# AGENTS.md

Static, dependency-free bilingual (Macedonian/English) catalogue of works by
Dragan Gjakonovski - Shpato held in the MRTV phonotheque.

There is no `package.json`, no bundler, no test runner, no linter and no CI.
The build is Python 3 standard library; the app is browser-native ES5-style
JavaScript. Keep both that way.

## Commands

```bash
python3 tools/build.py          # sources/*.csv -> data/catalog.* + data/notes.*
python3 -m http.server 8000     # http://localhost:8000/
git status --short              # after a build: must be clean
```

`index.html` also works over `file://`, and that must keep working: no
`fetch()` of local data, no ES modules, no `import`. Generated data is loaded
as plain `<script>` globals.

## Repo map

```
index.html              the whole app shell (five views, drawer, consent bar)
assets/styles.css       theme tokens + all styling
assets/i18n.js          every user-visible string, mk + en
assets/app.js           all behaviour
assets/fonts/*.woff2    self-hosted Geologica (the only typeface, OFL 1.1)
assets/images/          cover, brand icon, About photograph, favicon set
tools/build.py          normalizer: sources -> data
tools/youtube-search.py candidate finder for the link map (dev-only)
tools/cover.html        1920x1080 social cover render target (dev-only)
tools/favicon.html      favicon render target (dev-only)
data/catalog.json|.js   generated, committed
data/notes.json|.js     generated, committed
sources/*.csv           monograph exports, the build's input
sources/youtube.csv     record -> YouTube video map (checked and machine-found), the build's input
sources/removals.csv    hand-curated rows the source repeats, the build's input
robots.txt              crawl policy (see Deployment)
sitemap.xml             the one canonical URL (see Deployment)
```

Script order in `index.html` is load-bearing: `data/catalog.js`,
`data/notes.js`, `assets/i18n.js`, `assets/app.js`.

## Data workflow

`sources/*.csv` are the input. `data/*` is **generated and committed** — never
edit it by hand. To fix data:

1. edit the CSV (this is expected; "untouched" below means the *build* does not
   rewrite them, not that they are frozen),
2. run `python3 tools/build.py`,
3. commit the CSV **and** the regenerated `data/*` together.

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

`sources/removals.csv` (`file,line,title,performer,signature`) lists rows the
source holds twice and the catalogue therefore carries once. `drop_rows()` runs
**after** the ids are handed out: a drop made earlier would shift every later
id in that category and send `sources/youtube.csv` at the wrong works. `line` is
the weakest thing to key a deletion on, so the other three columns are guards —
checked against the record and reported, never applied, when they disagree — and
a row is only ever dropped when another row shares its `duplicate_key()`.

Every normalization must be recorded in the notes pipeline (`textFixes` /
`flags`, with a `SEVERITY` entry) or it is invisible in the Забелешки tab.
Never "fix" a title or name silently. A dropped row is recorded there too, under
`duplicate-dropped`: it has no record left to carry a flag.

## YouTube links

`sources/youtube.csv` (`id,title,video,found,lengthSec`) is the link map, part
hand-checked and part machine-filled. `id` is positional (`vocal-0007`), so
`title` is a guard: `attach_videos()` warns when it disagrees with the record,
because a shifted id would otherwise attach a video to the wrong work with no
visible symptom. A value that is not a valid 11-character id (or a pasted
YouTube URL) is dropped with a warning. The field is present on every record,
`null` when unknown.

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

What the finder accepts, and why it is loose: the point of a link is that the
reader can hear the work, not that the phonotheque's copy has been identified,
so duration never rejects a candidate — "Blagoja Ceslarov - Aranhuez" is 90 s
off the catalogue's timing and is still the right piece. A candidate is
accepted when its title carries the work's title and something ties it to the
performer or arranger: a distinctive word of the performer's name in the video
title, two of them anywhere on the page, an upload on a channel a hand-verified
link already came from, or the arranger credited (`CREDIT_WORDS`). `ROLE_WORDS`
is what stops "ТО на РТС" from matching on "РТС" alone, which is on half the
archive.

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
`ROLE_WORDS` and `CREDIT_WORDS`, or the fixed sets would never meet a folded
page. Where the artist is named inside the video title matters more than where
it is not: requiring it in the title is what rejected two unrelated videos that
matched "Балада за гитара — Петар Лукиќ" on "petar" sitting in an uploader's
channel name.

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
- A one-word title is a weak identity, so `accept()` asks for the performer's
  name in full when the title has a single word — both words of "Зоран
  Георгиев", so that "Zašto je uspjeh najveća iluzija?" by a host called Zoran
  cannot become the song "Илузија" — or, when the name is itself one word, that
  one word ("Импулси"), or a trusted channel. Measured on the selftest, the
  stricter form cost one hand-checked link (a one-word band name) until it was
  written this way. Requiring the name *regardless* of the channel was measured
  over the 122 links a pass had written: it refused 21, and almost all were a
  different *recording of the right song* on a channel a hand-checked link had
  come from ("Идила" by Никола Комовски as "Идила - Нина Спирова") — the class
  this catalogue accepts and marks — so the trusted channel keeps its standing
  and the two rows such as "Адиос" becoming "Ljupka Dimitrovska - Adios Amor"
  are the price.
- `dedupe_picks()` — with 38 titles naming more than one work, one upload can
  pass the test for two of them; a scan keeps it for one work only.

A *candidate's* duration is still never used to confirm anything: the build
alone marks, and only within `VIDEO_DURATION_TOLERANCE`.

The chain runs title+performer, its core, both romanised, the title alone, the
performer alone and title+Шпато, stopping at the first query that yields an
accepted candidate. `--selftest` replays the hand-verified links as unknown,
with each work's own channel left out of the trusted set, and measures the
rule: 38/39 recovered, 33 as the best pick (the miss is an upload titled
"Indiana" for "Индијана"). Run it before changing the rule, and read the
measured numbers rather than guessing.

Only `--apply` writes: new rows go in with `found=search`, and a row that
already has a video is never overwritten or re-searched. The finder reuses
`to_latin()` from `build.py` rather than growing a third transliteration.

Where the pass over the 361 works that were still unlinked left the catalogue:
162 of 433 works carry a link, 120 of them machine-found — vocal 38/74,
instrumental 23/55, arrThemes 9/43, arrVocal 92/261 — with the rest of the
catalogue offered as a YouTube search from the drawer instead. A machine-found
link that is not within `VIDEO_DURATION_TOLERANCE` of the catalogue's timing is
marked, so the reader is told, and the five links a re-audit refused are simply
not there.

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

## Analytics and the privacy notice

`index.html` carries a Google Analytics 4 tag (`G-Z2QYKW1QNC`), and it is not
loaded until the reader allows it. The `<head>` sets Consent Mode's defaults with
every signal denied, and it is `assets/app.js` that fetches `gtag.js` at all: the
decision lives in `localStorage["shpato-consent"]`, an undecided reader gets the
bar, `granted` loads the tag, `denied` means nothing is ever requested from
Google. Withdrawing is as easy as granting — `privacy.choice` reopens the bar
from the notice — and it clears the `_ga*` cookies the tag left, on the host and
on the registrable domain, because the tag takes the registrable one when it can.
If the tag had already loaded it also reloads the page, since a tag in memory
cannot be taken out and consent-denied GA goes on sending cookieless pings; the
choice is stored first, so the reload comes back refused, with no bar. Do not
"simplify" this into an eager tag plus `consent update`: that still pings Google
before a choice, which is the thing the bar exists to prevent.

The bar is `position: fixed` rather than a row of the shell, because on a phone
the shell has stood down and the document scrolls: in the flow it would sit at
the end of the catalogue and only be met by scrolling there. What the shell gives
up instead is exactly its height, measured into `--consent-h` and spent as
`body.app`'s bottom padding — the same bargain `main`'s bottom padding strikes
with the footer, and the reason the footer is never behind the bar. It comes
first in the document so a keyboard reader meets it before 433 rows, while it
paints at the bottom; its controls are buttons, not links, because they change
the page's state rather than navigating anywhere. Print drops it, reduced motion
drops its slide-in, and the drawer makes it inert like the rest of the page.

`#view-privacy` is the notice, the one view with no tab of its own: the strip is
sized for four, so it is reached from the footer's `#privacy-link` and from the
bar's "What is collected?". Both call `setTab("privacy")` and then put focus on
its heading, since no tab exists to announce the switch, and its `role` is
`region` rather than `tabpanel` for the same reason: nothing controls it.
`setTab` keeps the first tab in the roving tabindex when the active view has no
tab of its own, or the whole strip would drop out of the tab order; `t("tab.privacy")`
exists for the document title alone.

Every sentence there is `privacy.*` prose in both languages, like `about.*`, and
it deliberately carries no "last updated" date: that date would have to be
hand-edited at every change and would go stale without anything noticing, the
same reason the build payload has no timestamp. What it says is what is true
today — GA4's `_ga` cookies last two years, the property's default retention is
two months, Google Ireland processes and Google LLC receives under the EU–US Data
Privacy Framework, the player is `youtube-nocookie.com` and fetches nothing until
a recording is pressed, and the site's own three `localStorage` keys
(`shpato-theme`, `shpato-lang`, `shpato-consent`) are functional and never
transmitted. If any of that changes, the notice has to change with it.

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
  the same line. The credit sits at its left — carrying the notice's door,
  `#privacy-link`, in the footer's own neutral colour and with `.5rem` in front
  of it, half the `1rem` that separates the two groups — and a group of four
  sharing links at its right: 1.5rem targets, the smallest that still clears the
  24px minimum, held apart by `justify-content: space-between`. The 620px block
  turns that into `center`, so on a phone the pair sits centred, and each of them
  on its own line once they wrap. That door moved the wrap: the pair fits one row
  from 463px up (455 before the space in front of it), where the four share
  links' `.5rem` gap used to end the row at 375. It costs the catalogue nothing,
  because below 620px the shell has stood down and the document scrolls, so a
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
- From 1024px up the facet panel is a permanent left pane
  (`clamp(260px, 32vw, 500px)`). Below that it is a disclosure above the table,
  opened from a handle in the toolbar (`#filters-toggle`, the export menu's
  `aria-expanded` + `hidden` idiom: no modal, no focus trap). Closed, the table
  keeps the whole pane; open, `.layout:has(.filters:not([hidden]))` splits it
  45/55 so neither can push the other out of sight. The panel takes the smaller
  share because it scrolls inside its own half and the table does not.
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
  nothing but itself. The consent bar's height is added to that room, because the
  player stands above the bar rather than over it: the bar's buttons sit at the
  right, exactly where the player docks, and an undecided reader has to be able to
  answer the bar while the work plays.

The check that matters when touching any of this is positional: with the shell up,
scroll the table to its end and the header, the tab bar, the facet sidebar and the
footer must not have moved, and the pane must not have gained a scrollbar of its
own.

## Conventions

- **All UI text is bilingual.** Adding a key means adding it to *both* `mk` and
  `en` in `assets/i18n.js`. `t()` falls back to English silently, so a missing
  Macedonian key will not throw — it will just ship English. Keys are currently
  at parity (187 each).
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
  to fill the column. Its items start at the top of the line and the button
  then drops by `calc((1lh - 1.3rem) / 2)`, so the icon centres on the title's
  *first* line: centring it in the line instead centres it on the whole title,
  which on a phone is two or three lines, and the icon hangs beside the
  second. `1lh` is derived from the inherited line-height rather than chosen,
  and `flex-shrink: 0` on the button is not what keeps it round — nothing in a
  table cell shrinks it. The warning badge keeps the old centring, because it
  trails the title rather than leading it. The circle's hit area is bigger than
  the circle: a pseudo-element takes it to 40x45px, which stays 3px inside the
  row's top and 4px inside its bottom (the cell's `.85rem` of vertical padding
  is the room) and 1px short of the title button 8px to its right, so a thumb
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
- The drawer is a modal: `setPageInert()` marks every `body > *` except
  `#drawer` and `#player` inert, and focus returns to the row that opened it.
- There is exactly one `<iframe>` in the app, in `#player-frame`, created on
  demand and removed by `stopPlayer()`. Nothing is embedded on load, and
  removing the element (not hiding it) is what stops the audio. `#player`
  outranks the drawer in `z-index` and steps clear of it above 900px, so a work
  keeps playing, and stays controllable, with the details open.
- `state.onlyVideo` is dropped from a deep link when `meta.videos` is 0, and the
  checkbox is hidden then, so a stale link cannot land on an empty table.
- Exact duplicates are collapsed at build time, not hidden in the app: the
  catalogue carries one row per item and Забелешки says which row of the source
  was left out and which one stayed (`Нормализирано` names the surviving work
  rather than its id). There is no "show duplicates" control, and nothing in the
  app filters on `duplicateOf` any more. The note for a dropped row names a
  record that is not in the catalogue, so `renderNotes()` gives that row
  `no-record` and a plain title instead of a button that would open nothing.
- The four footer sharing links are share *intents*, not profile links: what is
  passed on is the catalogue. `renderShareLinks()` builds their hrefs from
  `<link rel="canonical">` rather than `location.href`, so they still name the
  site when the page was opened from disk, where a `file:` URL would mean
  nothing to whoever received it. The labels come from `share.*`; the glyphs are
  inline Simple Icons paths (CC0).
- Transliteration exists twice on purpose: `toLatin()` in `app.js` normalises
  the *query*, `to_latin()` in `build.py` bakes the *index* (`rec.search`, which
  is built at build time). Change one and check the other, or search breaks.
- Commit messages are imperative mood, sentence case, no prefix.

## Accessibility

The bar is **zero axe-core violations** in both themes, on all four tabs, with
the drawer open, the export menu open and the player open. Re-check it after any
markup change. axe's `incomplete` items on `#export-btn`, the scrollable facet
panel and one-character count chips are pre-existing false positives, not
regressions.

Focus order is keyboard-complete; the catalogue table's row buttons alone are
433 tab stops, plus one more for each of the 39 play buttons, so avoid adding
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

## Deployment

GitHub Pages via `CNAME` (`shpato.gocemitevski.com`). Pushing `master`
publishes the site. `index.html` carries real OG/Twitter tags and a Google tag
(`G-Z2QYKW1QNC`) that only loads once the reader allows it — see Analytics and
the privacy notice above; keep the canonical and absolute image URLs in step with
the domain if either changes.

Pages serves `index.html` at both `/` and `/index.html` with no redirect, so
there are two URLs for one document. The canonical names the root; `robots.txt`
keeps crawlers off `/index.html` so no audit has to reconcile the pair, and it
deliberately does *not* disallow `assets/` or `data/`, which Google fetches to
render the page. `sitemap.xml` lists the one URL — the tabs and the search live
in the fragment, and a fragment is not a page. The two `tools/*.html` render
targets are published like everything else, so each carries
`<meta name="robots" content="noindex">`; they are not pages and want no
canonical.
