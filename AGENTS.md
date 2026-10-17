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
not proof.

The finder searches a work by title **and** performer first, and widens to the
romanised form and only then to the title alone, each step running only while
nothing found so far shares a real word with the work. That order is measured,
not taste: against the 23 curated links the strict query reaches 23/23,
romanised 22/23, title-only 13/23 — YouTube matches across scripts by itself,
and 38 titles are shared by more than one work. So widening mostly shows junk
for works that are simply not on YouTube; it is a last look, not a routine
step. The finder reuses `to_latin()` from `build.py` rather than growing a
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
  the same line.
- `.filters` and `.table-wrap` set `overscroll-behavior: contain`: a wheel that
  reaches the end of a facet list or of the table stops there instead of
  carrying on into the shell.
- From 1024px up the facet panel is a permanent left pane
  (`clamp(260px, 32vw, 500px)`). Below that it is a disclosure above the table,
  opened from a handle in the toolbar (`#filters-toggle`, the export menu's
  `aria-expanded` + `hidden` idiom: no modal, no focus trap). Closed, the table
  keeps the whole pane; open, `.layout:has(.filters:not([hidden]))` splits it
  55/45 so neither can push the other out of sight, and the panel scrolls inside
  its share.
- The width is the script's business too, through those same two breakpoints:
  `matchMedia("(min-width: 1024px)")` hands the panel over — wide, it is simply
  there and the handle is hidden; narrow, the handle shows and the panel starts
  closed — and `matchMedia("(max-width: 620px)")` hides `#app-subtitle`. The
  widths are written out in the stylesheet and in `app.js` by hand, so changing
  one means changing the other.
- Below 620px the mark also shrinks to 40px, and the search gives up its 320px
  basis so the handle shares its row instead of costing a row of its own.
- Below 600px of *viewport height* the shell stands down
  (`@media (max-height: 600px)`) and the page scrolls as a document again. A
  window that short has no room for the header, the toolbar and a table worth
  reading. The print block undoes the shell for the same kind of reason: a
  printer wants the whole catalogue, not one clipped viewport of a scroll pane.
- `setTab()` sets `main.scrollTop = 0`. With the document no longer scrolling,
  nothing else moves the pane when the tab changes.
- `body.player-open` reserves the player's room inside `.table-wrap` and `.view`,
  never by padding `main`: padding `main` would make the shell scroll to reveal
  nothing but itself.

The check that matters when touching any of this is positional: scroll the table
to its end and the header, the tab bar, the facet sidebar and the footer must not
have moved.

## Conventions

- **All UI text is bilingual.** Adding a key means adding it to *both* `mk` and
  `en` in `assets/i18n.js`. `t()` falls back to English silently, so a missing
  Macedonian key will not throw — it will just ship English. Keys are currently
  at parity (146 each).
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
  to fill the column.
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
433 tab stops, plus one more for each of the 23 play buttons, so avoid adding
anything focusable per row without thinking about it.

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
