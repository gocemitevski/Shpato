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
index.html              the whole app shell (four views + drawer)
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
sources/youtube.csv     hand-curated record -> YouTube video map, the build's input
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

Every normalization must be recorded in the notes pipeline (`textFixes` /
`flags`, with a `SEVERITY` entry) or it is invisible in the Забелешки tab.
Never "fix" a title or name silently.

## YouTube links

`sources/youtube.csv` (`id,title,video`) is curated by hand, not derived. `id`
is positional (`vocal-0007`), so `title` is a guard: `attach_videos()` warns
when it disagrees with the record, because a shifted id would otherwise
attach a video to the wrong work with no visible symptom. A value that is not
a valid 11-character id (or a pasted YouTube URL) is dropped with a warning.
The field is present on every record, `null` when unknown.

`tools/youtube-search.py` proposes candidates by scraping YouTube's public
search page. It is a convenience, never a build step, and it does not decide:
every line of `sources/youtube.csv` was read by a human. Video length is
compared against `durationSec` and marked when it agrees — a useful signal,
not proof. Check it against the *other* records that share the title too: 38
catalogue titles name more than one work, and a candidate whose length fits a
sibling record's `durationSec` better than its own is very likely that
sibling's recording. (A full pass with this tool over the 411 unlinked works
found 15 links; the corpus is mostly not on YouTube.)

The finder searches a work by title **and** performer first, and widens to the
romanised form and only then to the title alone, each step running only while
nothing found so far shares a real word with the work. That order is measured,
not taste: against the 39 curated links the strict query reaches 39/39,
romanised 36/39, title-only 30/39 — YouTube matches across scripts by itself,
and 38 titles are shared by more than one work. So widening mostly shows junk
for works that are simply not on YouTube; it is a last look, not a routine
step — over the 411 unlinked works the chain averaged 1.07 searches per work.
The finder reuses `to_latin()` from `build.py` rather than growing a
third transliteration.

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
  the same line. The credit sits at its left and a group of four sharing links
  at its right: 1.5rem targets, the smallest that still clears the 24px minimum,
  held right by `margin-left: auto` rather than `justify-content`, which would
  leave a group that wraps onto a line of its own at the *start* of that line.
  Below about 340px the credit and the group stop fitting side by side and the
  footer grows a second row; that is the wrap behaving, not a bug.
- `.filters` and `.table-wrap` set `overscroll-behavior: contain`: a wheel that
  reaches the end of a facet list or of the table stops there instead of
  carrying on into the shell.
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
- Below 620px the mark also shrinks to 48px, and the search gives up its 320px
  basis so the handle shares its row instead of costing a row of its own. The
  four tabs need 443px at the default gap and size and a phone offers 361 of
  them, so the strip tightens too — `.78rem` labels and `.75rem` gaps, and
  `.7rem` with `.4rem` gaps under 360px (a 320px phone, or a window at 200%
  zoom). The last tab used to hang off the edge: swipeable, but with nothing
  showing that it was. The strip's own padding stays where `main`'s is, so the
  first tab still lines up with the table. The subtitle is *not* dropped there:
  it wraps to two lines and the header costs the pane 23px for it, which is
  cheaper than the empty band it looks like without one. It is only the mark
  that the breakpoint touches, and `text-wrap: balance` keeps the two lines from
  ending on "МРТВ".
- The shell stands down in two windows. Below 600px of *viewport height*
  (`@media (max-height: 600px)`) there is no room for the header, the toolbar
  and a table worth reading. Below 620px of *width* — a phone — the shell costs
  more than it gives: at 393x851 the pinned chrome took 356px of 851 and left the
  table 380px, about seven rows, and with no document to scroll the browser's
  address bar could never collapse to give any of it back. Stood down, the table
  has the whole page and the tab bar still sticks to the top (the document is the
  scrollport now); what is given up is the sticky column header, because the card
  is no longer a scroll container and its `thead` has nothing to stick to, so the
  five sort buttons live at the head of the table. The print block undoes the
  shell for the same kind of reason: a printer wants the whole catalogue, not one
  clipped viewport of a scroll pane.
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
  jump is made with `scroll-behavior` temporarily `auto`.
- `body.player-open` reserves the player's room inside `.table-wrap` and `.view`,
  never by padding `main`: padding `main` would make the shell scroll to reveal
  nothing but itself.

The check that matters when touching any of this is positional: with the shell up,
scroll the table to its end and the header, the tab bar, the facet sidebar and the
footer must not have moved.

## Conventions

- **All UI text is bilingual.** Adding a key means adding it to *both* `mk` and
  `en` in `assets/i18n.js`. `t()` falls back to English silently, so a missing
  Macedonian key will not throw — it will just ship English. Keys are currently
  at parity (151 each).
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
  trails the title rather than leading it.
- `[hidden] { display: none !important }` is the only hide mechanism. Use the
  `hidden` property/attribute, not classes.
- `* { box-sizing: border-box }` is global, so a fixed `width` includes padding.
- Theme is the `data-theme` attribute on `<html>` plus
  `localStorage["shpato-theme"]`, with an inline anti-flash script in the
  `<head>` resolving the OS preference. That script must stay inline and before
  the stylesheet. Language is `localStorage["shpato-lang"]`.
- `--theme-color` is mirrored into `<meta name="theme-color">` by
  `syncThemeColor()`; add new tokens to `:root` and both theme blocks.
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
- `state.showDuplicates` is **on by default**: the catalogue is a record of what
  the phonotheque holds, and a duplicate is one of its records. Off is the
  serialised non-default (`dup=0`), and `deserialize()` reads the parameter only
  when the hash carries one — reading it unconditionally would send every link
  without a `dup` back to the off state.
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
434 tab stops, plus one more for each of the 39 play buttons, so avoid adding
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
(`G-Z2QYKW1QNC`); keep the canonical and absolute image URLs in step with the
domain if either changes.

Pages serves `index.html` at both `/` and `/index.html` with no redirect, so
there are two URLs for one document. The canonical names the root; `robots.txt`
keeps crawlers off `/index.html` so no audit has to reconcile the pair, and it
deliberately does *not* disallow `assets/` or `data/`, which Google fetches to
render the page. `sitemap.xml` lists the one URL — the tabs and the search live
in the fragment, and a fragment is not a page. The two `tools/*.html` render
targets are published like everything else, so each carries
`<meta name="robots" content="noindex">`; they are not pages and want no
canonical.
