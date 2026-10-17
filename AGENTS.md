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
index.html              the whole app shell (three views + drawer)
assets/styles.css       theme tokens + all styling
assets/i18n.js          every user-visible string, mk + en
assets/app.js           all behaviour
assets/fonts/*.woff2    self-hosted Geologica (the only typeface, OFL 1.1)
assets/images/          cover, brand icon, favicon set (transparent PNGs)
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

YouTube will not play an embed on a page with no origin: Chrome sends no
referrer for `file://`, and the player answers with "configuration error 153"
for every embed host, `referrerpolicy` and `origin` parameter combination
tried. `file://` support is a hard requirement here, so `CAN_EMBED` is false
there and the play button opens the video on YouTube in a new tab instead of
mounting a player that can only fail. Do not "simplify" that branch away.

## Conventions

- **All UI text is bilingual.** Adding a key means adding it to *both* `mk` and
  `en` in `assets/i18n.js`. `t()` falls back to English silently, so a missing
  Macedonian key will not throw — it will just ship English. Keys are currently
  at parity (122 each).
- **Capitalisation lives in the strings, not in CSS.** A `<select>`'s
  `<option>` does not inherit `text-transform`, so a CSS-capitalised label looks
  right in the table and wrong in a dropdown. Capitalise in `i18n.js`.
- All user-visible strings go through `data-i18n` / `t()`; no hard-coded prose
  in `index.html` or `app.js`.
- The branded categories are driven by a single `data-cat` attribute that
  resolves to the inheritable `--cat` / `--cat-soft` custom properties. Don't
  special-case a category in JS.
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

The bar is **zero axe-core violations** in both themes, on all three tabs, with
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
