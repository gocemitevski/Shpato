/* Shpato digital catalogue - vanilla JS, no dependencies. */
(function () {
  "use strict";

  var CATALOG = window.CATALOG || { meta: {}, records: [] };
  var NOTES = window.NOTES || { notes: [] };
  var RECORDS = CATALOG.records;
  var META = CATALOG.meta;
  var DATA_MIN = 0;
  var DATA_MAX = (function () {
    var max = 0;
    RECORDS.forEach(function (r) { if (r.durationSec && r.durationSec > max) max = r.durationSec; });
    return Math.max(60, Math.ceil(max / 30) * 30);
  })();

  var CATEGORY_ORDER = ["vocal", "instrumental", "arrThemes", "arrVocal"];
  var TABS = ["catalog", "stats", "notes", "about"];
  // The columns that carry a data-sort attribute in index.html.
  var SORT_KEYS = ["title", "performer", "composer", "durationSec", "signature"];
  var facetFilterState = {};
  var facetOpenState = { "facet-category": true, "facet-performer": true, "facet-duration": true  };

  var state = {
    lang: localStorage.getItem("shpato-lang") || "mk",
    theme: document.documentElement.getAttribute("data-theme") || "light",
    tab: "catalog",
    query: "",
    categories: new Set(),
    collections: new Set(),
    composers: new Set(),
    performers: new Set(),
    durMin: DATA_MIN,
    durMax: DATA_MAX,
    sort: { key: "title", dir: "asc" },
    showDuplicates: false,
    onlyVideo: false,
    selected: null,
    noteSeverity: "",
    noteRule: "",
    noteLimit: 60
  };

  var lastFocused = null;
  var playing = null;  // id of the record in the mini-player, if any

  // ------------------------------------------------------------------ i18n
  function t(key) {
    var table = window.I18N[state.lang] || window.I18N.mk;
    return table[key] || (window.I18N.en[key] || key);
  }
  function categoryLabel(c) { return t("cat." + c); }
  function categoryShort(c) { return t("cat.short." + c); }

  // ------------------------------------------------------------- formatting
  function fmt(sec) {
    if (sec === null || sec === undefined) return t("common.none");
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ":" + String(s).padStart(2, "0");
  }
  function fmtLong(sec) {
    if (!sec) return t("common.none");
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    if (h) return h + t("unit.hour") + " " + m + t("unit.min");
    return m + t("unit.min") + " " + s + t("unit.sec");
  }
  function num(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0"); }

  function esc(str) {
    return String(str).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------------------------------------------------------- translit keys
  var TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ѓ": "gj", "е": "e",
    "ж": "zh", "з": "z", "ѕ": "dz", "и": "i", "ј": "j", "к": "k", "л": "l",
    "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "ќ": "kj", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "џ": "dj", "ш": "sh"
  };
  function toLatin(text) {
    return text.toLowerCase().replace(/[\u0400-\u04ff]/g, function (ch) { return TRANSLIT[ch] || ch; });
  }
  function normalize(s) { return (s || "").toLowerCase().trim(); }

  // ------------------------------------------------------------- filtering
  function isDuplicate(r) { return r.duplicateOf !== null && r.duplicateOf !== undefined; }

  function matchesQuery(r, q) {
    if (!q) return true;
    return q.split(/\s+/).every(function (part) {
      if (!part) return true;
      return r.search.indexOf(part) !== -1 || r.search.indexOf(toLatin(part)) !== -1;
    });
  }

  function filtered() {
    var q = normalize(state.query);
    var durActive = state.durMin > DATA_MIN || state.durMax < DATA_MAX;
    var list = RECORDS.filter(function (r) {
      if (!state.showDuplicates && isDuplicate(r)) return false;
      if (state.onlyVideo && !r.video) return false;
      if (state.categories.size && !state.categories.has(r.category)) return false;
      if (state.collections.size && !state.collections.has(r.collection || "__none__")) return false;
      if (state.composers.size && !state.composers.has(r.composer || "__none__")) return false;
      if (state.performers.size && !state.performers.has(r.performer || "__none__")) return false;
      if (durActive) {
        if (r.durationSec === null) return false;
        if (r.durationSec < state.durMin || r.durationSec > state.durMax) return false;
      }
      return matchesQuery(r, q);
    });
    return sortList(list);
  }

  function sortList(list) {
    var key = state.sort.key, dir = state.sort.dir === "desc" ? -1 : 1;
    return list.sort(function (a, b) {
      var av = a[key], bv = b[key];
      if (key === "durationSec") {
        if (av === null && bv === null) return 0;
        if (av === null) return 1;
        if (bv === null) return -1;
      }
      if (typeof av === "string" || typeof bv === "string") {
        av = av || ""; bv = bv || "";
        return av.localeCompare(bv, "mk") * dir;
      }
      return ((av || 0) - (bv || 0)) * dir;
    });
  }

  // Counts per facet value. `includeHidden` ignores the "show duplicates"
  // toggle, which the statistics need: they describe the whole catalogue and
  // must not shift when that box is ticked.
  function facetCounts(field, includeHidden) {
    var map = new Map();
    RECORDS.forEach(function (r) {
      if (!includeHidden && !state.showDuplicates && isDuplicate(r)) return;
      var v = r[field] || (field === "collection" ? "__none__" : "");
      if (!v) return;
      map.set(v, (map.get(v) || 0) + 1);
    });
    return map;
  }

  // --------------------------------------------------------------- rendering
  function updateTitle() {
    document.title = t("app.title") + " - " + t("tab." + state.tab);
  }

  function renderStatic() {
    document.documentElement.lang = state.lang;
    updateTitle();
    document.getElementById("app-title").textContent = t("app.title");
    document.getElementById("app-subtitle").textContent = t("app.subtitle");
    document.getElementById("search").placeholder = t("search.placeholder");
    document.getElementById("show-duplicates-label").textContent = t("results.showDuplicates");
    // The "with a video" filter is only worth showing when something can play.
    document.getElementById("only-video-wrap").hidden = !META.videos;
    document.getElementById("only-video-label").textContent =
      t("results.onlyVideo").replace("{n}", num(META.videos || 0));
    document.getElementById("filters-title").textContent = t("filters.title");
    document.getElementById("clear-filters").textContent = t("filters.clear");

    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-label]").forEach(function (el) {
      el.setAttribute("aria-label", t(el.getAttribute("data-i18n-label")));
    });

    document.querySelectorAll("#tabs button").forEach(function (btn) {
      var tab = btn.getAttribute("data-tab");
      btn.textContent = t("tab." + tab);
      btn.setAttribute("aria-selected", tab === state.tab ? "true" : "false");
    });

    document.querySelectorAll(".lang-toggle button").forEach(function (btn) {
      btn.setAttribute("aria-pressed", btn.getAttribute("data-lang") === state.lang ? "true" : "false");
    });

    var themeToggle = document.getElementById("theme-toggle");
    themeToggle.querySelectorAll("button").forEach(function (btn) {
      var theme = btn.getAttribute("data-theme");
      btn.setAttribute("aria-pressed", theme === state.theme ? "true" : "false");
      btn.setAttribute("title", t("theme." + theme));
      btn.setAttribute("aria-label", t("theme." + theme));
    });

    document.querySelectorAll("th.sortable").forEach(function (th) {
      var key = th.getAttribute("data-sort");
      var label = th.querySelector(".th-label");
      if (label) label.textContent = t("col." + (key === "durationSec" ? "duration" : key));
      if (key === state.sort.key) {
        th.setAttribute("data-dir", state.sort.dir);
        th.setAttribute("aria-sort", state.sort.dir === "desc" ? "descending" : "ascending");
      } else {
        th.removeAttribute("data-dir");
        th.setAttribute("aria-sort", "none");
      }
    });

    // The counts ride in the option labels, so the select carries the summary on
    // its own: closed, it reads "Сите степени (420)" rather than a bare "Сите".
    var sev = severityCounts();
    document.querySelector("#note-severity option[value='']").textContent =
      t("notes.allSeverities") + " (" + sev.all + ")";
    document.querySelector("#note-severity [value='warning']").textContent =
      t("severity.warning") + " (" + sev.warning + ")";
    document.querySelector("#note-severity [value='info']").textContent =
      t("severity.info") + " (" + sev.info + ")";
    refreshRuleSelect();
    // The player's own labels are static, but its subtitle is built from the
    // record, so it has to be rebuilt when the language changes.
    if (playing) {
      var pr = RECORDS.find(function (x) { return x.id === playing; });
      if (pr) document.getElementById("player-sub").textContent = playerSubtitle(pr);
    }
  }

  function updateFacetBadge(el, n) {
    var summary = el.querySelector("summary");
    if (!summary) return;
    var badge = summary.querySelector(".facet-badge");
    if (n) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "facet-badge";
        summary.insertBefore(badge, summary.querySelector(".chev"));
      }
      badge.textContent = n;
    } else if (badge) {
      badge.remove();
    }
  }

  function facetShell(el, titleKey, open, selectedCount) {
    var badge = selectedCount ? '<span class="facet-badge">' + selectedCount + "</span>" : "";
    el.innerHTML = '<details class="facet"' + (open ? " open" : "") + ">" +
      "<summary><span>" + esc(t(titleKey)) + "</span>" + badge +
      '<span class="chev" aria-hidden="true">\u203a</span></summary>' +
      '<div class="facet-body"></div></details>';
    var details = el.querySelector("details");
    details.addEventListener("toggle", function () { facetOpenState[el.id] = details.open; });
    return details.querySelector(".facet-body");
  }

  function checkboxFacet(container, titleKey, entries, selectedSet, noneLabel, defaultOpen) {
    var el = document.getElementById(container);
    var open = facetOpenState[container];
    if (open === undefined) open = !!defaultOpen || selectedSet.size > 0;
    var body = facetShell(el, titleKey, open, selectedSet.size);

    var many = entries.length > 12;
    if (many) body.insertAdjacentHTML("beforeend",
      '<input class="facet-filter" type="search" placeholder="' + esc(t("filters.filterList")) +
      '" aria-label="' + esc(t("filters.filterList")) + '">');
    var list = document.createElement("div");
    list.className = "facet-list" + (many ? " facet-list--scroll" : "");
    list.innerHTML = entries.map(function (e) {
      var label = e.value === "__none__" ? noneLabel : (e.label || e.value);
      var checked = selectedSet.has(e.value) ? " checked" : "";
      var cat = e.cat ? ' data-cat="' + esc(e.cat) + '"' : "";
      var dot = e.cat ? '<span class="facet-dot" aria-hidden="true"></span>' : "";
      return '<label class="facet-item" data-search="' + esc(normalize(label)) + '"' + cat + ">" + dot +
        '<input type="checkbox" value="' + esc(e.value) + '"' + checked + ">" +
        "<span>" + esc(label) + '</span><span class="count">' + e.count + "</span></label>";
    }).join("");
    body.appendChild(list);

    var filter = body.querySelector(".facet-filter");
    if (filter) {
      function applyFacetFilter() {
        var q = normalize(filter.value);
        list.querySelectorAll(".facet-item").forEach(function (item) {
          item.hidden = q && item.getAttribute("data-search").indexOf(q) === -1;
        });
      }
      filter.value = facetFilterState[container] || "";
      applyFacetFilter();
      filter.addEventListener("input", function () {
        facetFilterState[container] = filter.value;
        applyFacetFilter();
      });
    }

    list.querySelectorAll("input[type=checkbox]").forEach(function (cb) {
      cb.addEventListener("change", function () {
        if (cb.checked) selectedSet.add(cb.value); else selectedSet.delete(cb.value);
        updateFacetBadge(el, selectedSet.size);
        refreshResults();
      });
    });
  }

  function renderFacets() {
    var cats = facetCounts("category");
    checkboxFacet("facet-category", "filters.category",
      CATEGORY_ORDER.filter(function (c) { return cats.get(c); }).map(function (c) {
        return { value: c, label: categoryShort(c), count: cats.get(c), cat: c };
      }), state.categories, "", true);

    var cols = facetCounts("collection");
    checkboxFacet("facet-collection", "filters.collection",
      Array.from(cols.keys()).sort().map(function (c) { return { value: c, count: cols.get(c) }; }),
      state.collections, t("common.unknown"));

    var comps = facetCounts("composer");
    checkboxFacet("facet-composer", "filters.composer",
      Array.from(comps.keys()).sort(function (a, b) { return a.localeCompare(b, "mk"); })
        .map(function (c) { return { value: c, count: comps.get(c) }; }),
      state.composers, "");

    var perfs = facetCounts("performer");
    checkboxFacet("facet-performer", "filters.performer",
      Array.from(perfs.keys()).sort(function (a, b) { return a.localeCompare(b, "mk"); })
        .map(function (p) { return { value: p, count: perfs.get(p) }; })
        .sort(function (a, b) { return b.count - a.count; }),
      state.performers, "");

    renderDurationFacet();
  }

  function renderDurationFacet() {
    var el = document.getElementById("facet-duration");
    var durActive = state.durMin > DATA_MIN || state.durMax < DATA_MAX;
    var open = facetOpenState["facet-duration"];
    if (open === undefined) open = durActive;
    var body = facetShell(el, "filters.duration", open, durActive ? 1 : 0);
    body.innerHTML =
      '<div class="range-row"><span id="dur-min-label">' + fmt(state.durMin) + '</span>' +
      '<input type="range" id="dur-min" min="' + DATA_MIN + '" max="' + DATA_MAX + '" step="15" value="' + state.durMin +
      '" aria-label="' + esc(t("filters.durMin")) + '" aria-valuetext="' + esc(fmt(state.durMin)) + '">' +
      "</div>" +
      '<div class="range-row"><span id="dur-max-label">' + fmt(state.durMax) + '</span>' +
      '<input type="range" id="dur-max" min="' + DATA_MIN + '" max="' + DATA_MAX + '" step="15" value="' + state.durMax +
      '" aria-label="' + esc(t("filters.durMax")) + '" aria-valuetext="' + esc(fmt(state.durMax)) + '">' +
      "</div>";
    var min = body.querySelector("#dur-min"), max = body.querySelector("#dur-max");
    min.addEventListener("input", function () {
      state.durMin = Math.min(+min.value, state.durMax);
      min.value = state.durMin;
      min.setAttribute("aria-valuetext", fmt(state.durMin));
      document.getElementById("dur-min-label").textContent = fmt(state.durMin);
      updateFacetBadge(el, state.durMin > DATA_MIN || state.durMax < DATA_MAX ? 1 : 0);
      refreshResults();
    });
    max.addEventListener("input", function () {
      state.durMax = Math.max(+max.value, state.durMin);
      max.value = state.durMax;
      max.setAttribute("aria-valuetext", fmt(state.durMax));
      document.getElementById("dur-max-label").textContent = fmt(state.durMax);
      updateFacetBadge(el, state.durMin > DATA_MIN || state.durMax < DATA_MAX ? 1 : 0);
      refreshResults();
    });
  }

  function renderResults() {
    var list = filtered();
    var body = document.getElementById("catalog-body");
    var empty = document.getElementById("catalog-empty");
    document.getElementById("result-meta").textContent =
      t("results.count").replace("{n}", num(list.length)).replace("{total}", num(META.total));

    empty.hidden = list.length > 0;
    empty.textContent = t("results.empty");

    body.innerHTML = list.map(function (r) {
      var warn = r.warnCount
        ? '<span class="badge" title="' + esc(t("detail.flags")) + '">' + r.warnCount +
          '<span class="visually-hidden"> ' + esc(t("detail.flags")) + "</span></span>"
        : "";
      // Only a work with a known video gets a play button, so the affordance
      // itself tells you what is listenable.
      var play = r.video
        ? '<button type="button" class="row-play" data-play="' + r.id + '" aria-label="' +
          esc(t("player.playAria").replace("{title}", r.title)) + '">' +
          '<svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">' +
          '<path d="M3.2 1.4 10 6 3.2 10.6Z"/></svg></button>'
        : "";
      return '<tr data-id="' + r.id + '">' +
        '<td class="cell-title"><span class="cell-title-inner">' + play +
        '<button type="button" class="row-open">' + esc(r.title) + "</button>" + warn +
        "</span></td>" +
        '<td class="cell-perf">' + esc(r.performer || t("common.none")) + "</td>" +
        '<td class="cell-comp">' + esc(r.composer || "") + "</td>" +
        '<td class="dur">' + fmt(r.durationSec) + "</td>" +
        '<td class="sig">' + esc(r.signature || r.signatureRaw || t("common.none")) + "</td>" +
        "</tr>";
    }).join("");
  }

  // ------------------------------------------------------------ mini-player
  // One player for the whole app, docked outside the drawer's modal, so a work
  // keeps playing while you filter, sort or read its details. The iframe is
  // built on demand and thrown away on stop — an embed that is merely hidden
  // goes on playing.
  function playerSubtitle(r) {
    return [r.performer, categoryLabel(r.category)].filter(Boolean).join(" · ");
  }

  function watchUrl(r) {
    return "https://www.youtube.com/watch?v=" + r.video;
  }

  // YouTube will not play an embed on a page with no origin: Chrome sends no
  // referrer for file://, and the player answers with "configuration error
  // 153", for every combination of embed host and referrer policy. Opening
  // index.html from disk is a supported way to use this app, so there the play
  // button opens the video on YouTube rather than mounting a player that can
  // only ever fail.
  var CAN_EMBED = location.protocol !== "file:";

  function youtubeSearchUrl(r) {
    var q = [r.title, r.performer].filter(Boolean).join(" ");
    return "https://www.youtube.com/results?search_query=" + encodeURIComponent(q);
  }

  function playRecord(id) {
    var r = RECORDS.find(function (x) { return x.id === id; });
    if (!r || !r.video) return;
    if (!CAN_EMBED) {
      window.open(watchUrl(r), "_blank", "noopener,noreferrer");
      return;
    }
    var player = document.getElementById("player");
    var frame = document.getElementById("player-frame");
    if (playing !== id) {
      playing = id;
      frame.innerHTML = "";
      var iframe = document.createElement("iframe");
      iframe.src = "https://www.youtube-nocookie.com/embed/" + r.video +
        "?autoplay=1&rel=0&playsinline=1";
      iframe.title = r.title;
      iframe.setAttribute("allow", "accelerometer; autoplay; clipboard-write; " +
        "encrypted-media; gyroscope; picture-in-picture; web-share");
      iframe.setAttribute("allowfullscreen", "");
      iframe.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
      frame.appendChild(iframe);
    }
    document.getElementById("player-title").textContent = r.title;
    document.getElementById("player-sub").textContent = playerSubtitle(r);
    document.getElementById("player-link").href = watchUrl(r);
    player.hidden = false;
    document.body.classList.add("player-open");
  }

  function stopPlayer() {
    if (playing === null) return;
    playing = null;
    document.getElementById("player-frame").innerHTML = "";  // this stops the audio
    document.getElementById("player").hidden = true;
    document.body.classList.remove("player-open");
  }

  // ---------------------------------------------------------------- drawer
  function setPageInert(on) {
    Array.prototype.forEach.call(document.body.children, function (el) {
      // The player stays live under the modal: a work must not go silent just
      // because its details are open. The drawer's own Tab trap still keeps
      // keyboard focus inside the dialog.
      if (el.id === "drawer" || el.id === "player") return;
      if (on) el.setAttribute("inert", "");
      else el.removeAttribute("inert");
    });
  }

  // The table row that opens a record, used as the focus return target. Both
  // tables carry record ids, and focusing a row inside a hidden view is a
  // no-op, so only a laid-out row counts.
  function rowButton(id) {
    var buttons = document.querySelectorAll('tr[data-id="' + id + '"] .row-open');
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].offsetParent !== null) return buttons[i];
    }
    return null;
  }

  function selectRecord(id, navigated) {
    state.selected = id;
    // Focus returns here when the drawer closes, so it tracks the record on
    // screen rather than whichever element happened to hold focus — clicking a
    // row's padding opens the drawer without focusing its title button.
    lastFocused = rowButton(id) || lastFocused;
    renderDrawer(navigated);
  }

  function renderDrawer(navigated) {
    var drawer = document.getElementById("drawer");
    var wasOpen = !drawer.hidden;
    var r = state.selected ? RECORDS.find(function (x) { return x.id === state.selected; }) : null;

    if (!r) {
      state.selected = null;
      drawer.hidden = true;
      if (wasOpen) {
        setPageInert(false);
        if (lastFocused && document.contains(lastFocused)) lastFocused.focus();
        lastFocused = null;
      }
      return;
    }
    drawer.hidden = false;

    function row(labelKey, value) {
      return "<dt>" + esc(t(labelKey)) + "</dt><dd>" + value + "</dd>";
    }
    var flags = r.flags.filter(function (f) { return f !== "duplicate"; });
    // The notes turn amber exactly when the row carries the amber badge in the
    // catalogue, so the same colour means the same thing in both places.
    var flagItems = flags.length
      ? '<ul class="flags' + (r.warnCount ? " flags-warn" : "") + '">' + flags.map(function (f) {
          return "<li>• " + esc(t("rule." + f)) + "</li>";
        }).join("") + "</ul>"
      : '<p class="empty-note">' + esc(t("detail.noFlags")) + "</p>";

    // A work with a known video plays from here too, through the same player,
    // so opening the details never interrupts what is already playing. A work
    // without one offers the search that would find it — "if they are found to
    // exist" includes letting the reader go and look.
    var playback = r.video
      ? '<div class="drawer-play"><button type="button" class="btn player-start" data-play="' +
        r.id + '"><svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">' +
        '<path d="M3.2 1.4 10 6 3.2 10.6Z"/></svg>' + esc(t("player.play")) + "</button></div>"
      : '<div class="drawer-play"><a class="search-link" href="' + esc(youtubeSearchUrl(r)) +
        '" target="_blank" rel="noopener">' + esc(t("player.search")) + "</a></div>";

    var related = "";
    related += relatedBlock("detail.sameTitle", RECORDS.filter(function (x) {
      return x.id !== r.id && x.title === r.title;
    }));
    related += relatedBlock("detail.samePerformer", r.performer ? RECORDS.filter(function (x) {
      return x.id !== r.id && x.performer === r.performer;
    }) : []);
    related += relatedBlock("detail.sameComposer", r.composer ? RECORDS.filter(function (x) {
      return x.id !== r.id && x.composer === r.composer;
    }) : []);

    document.getElementById("drawer-content").innerHTML =
      "<h2 id=\"drawer-title\" tabindex=\"-1\">" + esc(r.title) + "</h2>" +
      '<span class="cat-tag" data-cat="' + esc(r.category) + '">' + esc(categoryLabel(r.category)) + "</span>" +
      "<dl>" +
      row("detail.performer", esc(r.performer || t("common.none")) +
        (r.performerRole ? ' <span class="raw-hint">(' + esc(r.performerRole) + ")</span>" : "")) +
      (r.composer ? row("detail.composer", esc(r.composer)) : "") +
      row("detail.duration", fmt(r.durationSec) +
        (r.durationRaw && r.durationRaw !== "" ? ' <span class="raw-hint">(' + esc(r.durationRaw) + " " + esc(t("detail.raw")) + ")</span>" : "")) +
      row("detail.signature", "<code class=\"raw\">" + esc(r.signature || r.signatureRaw || t("common.none")) + "</code>" +
        (r.signature && r.signatureRaw && r.signature !== r.signatureRaw ? " <span class=\"raw-hint\">" + esc(r.signatureRaw) + "</span>" : "")) +
      (r.collection ? row("detail.collection", esc(r.collection)) : "") +
      row("detail.source", '<code class="raw raw-truncate" title="' + esc(r.sourceFile + ":" + r.sourceLine) + '">' + esc(r.sourceFile) + ":" + r.sourceLine + "</code>") +
      "</dl>" +
      playback +
      "<h3>" + esc(t("detail.flags")) + "</h3>" + flagItems +
      "<h3>" + esc(t("detail.related")) + "</h3>" +
      '<div class="related">' +
      (related || '<p class="empty-note">' + esc(t("detail.noRelated")) + "</p>") +
      "</div>";

    drawer.querySelectorAll("[data-goto]").forEach(function (btn) {
      btn.addEventListener("click", function () { selectRecord(btn.getAttribute("data-goto"), true); });
    });
    drawer.querySelectorAll("[data-play]").forEach(function (btn) {
      btn.addEventListener("click", function () { playRecord(btn.getAttribute("data-play")); });
    });

    if (!wasOpen) {
      setPageInert(true);
      var closeBtn = drawer.querySelector(".drawer-close");
      if (closeBtn) closeBtn.focus();
    } else if (navigated) {
      // Following a related-work link replaces the drawer's content, which
      // destroys the focused chip. Move focus to the new heading instead of
      // letting it fall to <body>, outside this modal.
      drawer.querySelector("#drawer-title").focus();
    }
  }

  function relatedBlock(titleKey, items) {
    if (!items.length) return "";
    var shown = items.slice(0, 15);
    // The list is capped, so say how many were left out rather than dropping
    // them silently.
    var more = items.length > shown.length
      ? '<p class="empty-note">' +
        esc(t("detail.moreRelated").replace("{n}", num(items.length - shown.length))) + "</p>"
      : "";
    return "<h3>" + esc(t(titleKey)) + "</h3><ul>" + shown.map(function (x) {
      return "<li><button class=\"chip-link\" data-goto=\"" + x.id + "\">" + esc(x.title) +
        " — " + esc(x.performer || t("common.none")) + "</button></li>";
    }).join("") + "</ul>" + more;
  }

  // ----------------------------------------------------------------- stats
  function renderStats() {
    var withDur = RECORDS.filter(function (r) { return r.durationSec !== null; });
    var totalDur = withDur.reduce(function (s, r) { return s + r.durationSec; }, 0);
    var performers = new Set(), composers = new Set();
    RECORDS.forEach(function (r) {
      if (r.performer) performers.add(r.performer);
      if (r.composer) composers.add(r.composer);
    });

    document.getElementById("stat-cards").innerHTML = [
      card(num(META.total), t("stats.total"), ""),
      card(fmtLong(totalDur), t("stats.duration"), num(withDur.length) + " " + t("stats.knownDuration")),
      card(fmt(Math.round(totalDur / Math.max(1, withDur.length))), t("stats.avg"), ""),
      card(num(performers.size), t("stats.performers"), ""),
      card(num(composers.size), t("stats.composers"), "")
    ].join("");

    bars("chart-category", CATEGORY_ORDER.map(function (c) {
      return { label: categoryLabel(c), value: META.counts[c] || 0, cat: c };
    }));
    bars("chart-collection", Array.from(facetCounts("collection", true).entries())
      .sort(function (a, b) { return b[1] - a[1]; })
      .map(function (e) { return { label: e[0] === "__none__" ? t("common.unknown") : e[0], value: e[1] }; }));
    bars("chart-performers", top(facetCounts("performer", true), 8));
    bars("chart-composers", top(facetCounts("composer", true), 8));
    bars("chart-duration", durationBuckets());
  }

  function top(map, n) {
    return Array.from(map.entries()).sort(function (a, b) { return b[1] - a[1]; })
      .slice(0, n).map(function (e) { return { label: e[0], value: e[1] }; });
  }

  function card(value, label, sub) {
    return '<div class="card"><div class="value">' + esc(value) + '</div><div class="label">' +
      esc(label) + "</div>" + (sub ? '<div class="sub">' + esc(sub) + "</div>" : "") + "</div>";
  }

  function bars(id, entries) {
    var max = Math.max.apply(null, [1].concat(entries.map(function (e) { return e.value; })));
    document.getElementById(id).innerHTML = entries.map(function (e) {
      var pct = e.value ? Math.max(2, Math.round((e.value / max) * 100)) : 0;
      var cat = e.cat ? ' data-cat="' + esc(e.cat) + '"' : "";
      return '<div class="bar-row"' + cat + '><span class="bar-label" title="' + esc(e.label) + '">' + esc(e.label) +
        '</span><span class="bar-track"><span class="bar-fill" style="width:' + pct + '%"></span></span>' +
        '<span class="bar-value">' + e.value + "</span></div>";
    }).join("");
  }

  function durationBuckets() {
    var size = 60;
    var maxRecord = 0;
    RECORDS.forEach(function (r) { if (r.durationSec && r.durationSec > maxRecord) maxRecord = r.durationSec; });
    var max = Math.max(size, Math.ceil(maxRecord / size) * size);
    var buckets = [];
    for (var s = 0; s < max; s += size) buckets.push({ from: s, to: s + size, value: 0 });
    if (maxRecord >= max) buckets.push({ from: max, to: Infinity, value: 0 });
    RECORDS.forEach(function (r) {
      if (r.durationSec === null) return;
      var idx = Math.min(Math.floor(r.durationSec / size), buckets.length - 1);
      buckets[idx].value++;
    });
    return buckets.map(function (b) {
      var label = b.to === Infinity ? t("stats.over") + " " + fmt(max)
        : fmt(b.from) + "–" + fmt(b.to);
      return { label: label, value: b.value };
    });
  }

  // ------------------------------------------------------------- notes
  function refreshRuleSelect() {
    var sel = document.getElementById("note-rule");
    var rules = new Set(NOTES.notes.map(function (a) { return a.rule; }));
    sel.innerHTML = '<option value="">' + esc(t("notes.allRules")) + "</option>" +
      Array.from(rules).sort().map(function (r) {
        return '<option value="' + esc(r) + '">' + esc(t("rule." + r)) + "</option>";
      }).join("");
    sel.value = state.noteRule;
  }

  // Severity counts, used as the option labels of the severity select.
  function severityCounts() {
    var all = NOTES.notes.length;
    var warning = NOTES.notes.filter(function (a) { return a.severity === "warning"; }).length;
    return { all: all, warning: warning, info: all - warning };
  }

  function renderNotes() {
    var list = NOTES.notes.filter(function (a) {
      if (state.noteSeverity && a.severity !== state.noteSeverity) return false;
      if (state.noteRule && a.rule !== state.noteRule) return false;
      return true;
    });
    var body = document.getElementById("note-body");
    var empty = document.getElementById("note-empty");
    empty.hidden = list.length > 0;
    empty.textContent = t("notes.empty");

    var shown = list.slice(0, state.noteLimit);
    body.innerHTML = shown.map(function (a) {
      var normalized = a.normalized;
      if (typeof normalized === "number" && a.rule.indexOf("duration") === 0) normalized = fmt(normalized);
      var ruleLabel = t("rule." + a.rule);
      if (a.field) ruleLabel += " · " + t("col." + a.field);
      return '<tr data-id="' + a.id + '">' +
        '<td class="cell-title"><button type="button" class="row-open">' + esc(a.title) + "</button></td>" +
        '<td class="rule">' + esc(ruleLabel) + "</td>" +
        '<td><span class="sev ' + a.severity + '">' + esc(t("severity." + a.severity)) + "</span></td>" +
        "<td>" + (a.raw ? '<code class="raw">' + esc(a.raw) + "</code>" : "") + "</td>" +
        "<td>" + esc(normalized === null || normalized === undefined ? "" : normalized) + "</td>" +
        '<td class="sig" title="' + esc(a.sourceFile) + ":" + a.sourceLine + '">' +
          esc(categoryShort(a.category)) + " · " + a.sourceLine + "</td>" +
        "</tr>";
    }).join("");

    document.getElementById("note-more").innerHTML = list.length > state.noteLimit
      ? '<button type="button" class="btn" id="note-show-all">' + esc(t("notes.showAll")) +
        " (" + list.length + ")</button>"
      : "";
  }

  // --------------------------------------------------------------- exports
  function download(filename, text, type) {
    var blob = new Blob([text], { type: type });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    // Revoking in the same task can cancel the download in Firefox.
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function csvCell(v) {
    v = v === null || v === undefined ? "" : String(v);
    return /[",\n;]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }
  function exportCSV() {
    var list = filtered();
    var header = ["id", "category", "title", "composer", "performer", "performerRole", "duration", "signature", "collection", "source"];
    var rows = list.map(function (r) {
      return [r.id, r.category, r.title, r.composer, r.performer, r.performerRole || "", fmt(r.durationSec),
        r.signature || r.signatureRaw, r.collection, r.sourceFile + ":" + r.sourceLine].map(csvCell).join(",");
    });
    download("shpato-catalog.csv", "\ufeff" + [header.join(",")].concat(rows).join("\n"), "text/csv;charset=utf-8");
  }
  function exportJSON() {
    var list = filtered();
    download("shpato-catalog.json", JSON.stringify({ meta: META, records: list }, null, 2), "application/json");
  }

  function closeExportMenu() {
    var menu = document.getElementById("export-menu");
    var btn = document.getElementById("export-btn");
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  }
  function toggleExportMenu() {
    var menu = document.getElementById("export-menu");
    var btn = document.getElementById("export-btn");
    var willOpen = menu.hidden;
    menu.hidden = !willOpen;
    btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
    if (willOpen) {
      var first = menu.querySelector('[role="menuitem"]');
      if (first) first.focus();
    }
  }

  // ------------------------------------------------------------- deep link
  function serialize() {
    var p = new URLSearchParams();
    p.set("tab", state.tab);
    if (state.query) p.set("q", state.query);
    if (state.categories.size) p.set("cat", Array.from(state.categories).join("|"));
    if (state.collections.size) p.set("col", Array.from(state.collections).join("|"));
    if (state.performers.size) p.set("perf", Array.from(state.performers).join("|"));
    if (state.composers.size) p.set("comp", Array.from(state.composers).join("|"));
    if (state.durMin > DATA_MIN) p.set("dmin", state.durMin);
    if (state.durMax < DATA_MAX) p.set("dmax", state.durMax);
    if (state.showDuplicates) p.set("dup", "1");
    if (state.onlyVideo) p.set("video", "1");
    if (state.sort.key !== "title" || state.sort.dir !== "asc") { p.set("sort", state.sort.key); p.set("dir", state.sort.dir); }
    return "#" + p.toString();
  }
  // A shared link is untrusted input, so every value read out of the hash is
  // validated against the data before it reaches the state.
  function knownValues(field, values) {
    var known = facetCounts(field, true);
    var out = new Set();
    values.forEach(function (v) { if (known.has(v)) out.add(v); });
    return out;
  }
  function readDuration(value, fallback) {
    var n = Number(value);
    if (!isFinite(n)) return fallback;
    return Math.min(DATA_MAX, Math.max(DATA_MIN, n));
  }

  function deserialize() {
    var raw = location.hash.replace(/^#/, "");
    if (!raw) return;
    var p = new URLSearchParams(raw);
    if (TABS.indexOf(p.get("tab")) !== -1) state.tab = p.get("tab");
    if (p.get("q")) state.query = p.get("q");
    if (p.get("cat")) state.categories = knownValues("category", p.get("cat").split("|"));
    if (p.get("col")) state.collections = knownValues("collection", p.get("col").split("|"));
    if (p.get("perf")) state.performers = knownValues("performer", p.get("perf").split("|"));
    if (p.get("comp")) state.composers = knownValues("composer", p.get("comp").split("|"));
    if (p.get("dmin")) state.durMin = readDuration(p.get("dmin"), DATA_MIN);
    if (p.get("dmax")) state.durMax = readDuration(p.get("dmax"), DATA_MAX);
    if (state.durMin > state.durMax) {
      var swap = state.durMin; state.durMin = state.durMax; state.durMax = swap;
    }
    state.showDuplicates = p.get("dup") === "1";
    // Ignore the flag when nothing in the catalogue has a video, or a stale
    // link would land on a permanently empty table.
    state.onlyVideo = p.get("video") === "1" && META.videos > 0;
    if (SORT_KEYS.indexOf(p.get("sort")) !== -1) {
      state.sort.key = p.get("sort");
      state.sort.dir = p.get("dir") === "desc" ? "desc" : "asc";
    }
  }

  // ------------------------------------------------------------------ main
  function setTab(tab) {
    state.tab = tab;
    // The shell does not scroll as a document, so the pane that does has to be
    // sent back to the top by hand: otherwise a tab opens part-way down
    // wherever the previous one was left.
    document.getElementById("main").scrollTop = 0;
    TABS.forEach(function (name) {
      document.getElementById("view-" + name).hidden = name !== tab;
    });
    document.querySelectorAll("#tabs button").forEach(function (btn) {
      var active = btn.getAttribute("data-tab") === tab;
      btn.setAttribute("aria-selected", active ? "true" : "false");
      btn.tabIndex = active ? 0 : -1;
    });
    updateTitle();
    if (tab === "stats") renderStats();
    if (tab === "notes") renderNotes();
  }

  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("shpato-theme", theme); } catch (e) {}
    syncThemeColor();
  }

  // The browser chrome colour lives in the palette as --theme-color, so it
  // cannot drift from the canvas it is meant to match.
  function syncThemeColor() {
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) return;
    var c = getComputedStyle(document.documentElement).getPropertyValue("--theme-color").trim();
    if (c) meta.setAttribute("content", c);
  }

  function persist() { history.replaceState(null, "", serialize()); }

  function refreshResults() {
    renderResults();
    if (state.tab === "stats") renderStats();
    persist();
  }

  function update() {
    renderFacets();
    refreshResults();
  }

  // ------------------------------------------------------- responsive chrome
  // The facet panel is a permanent pane from 1024px up and a disclosure below
  // that; on a phone the header then drops its subtitle. These widths are the
  // stylesheet's breakpoints, kept in step by hand.
  var mqWide = window.matchMedia("(min-width: 1024px)");
  var mqPhone = window.matchMedia("(max-width: 620px)");

  function setFiltersOpen(open) {
    document.getElementById("filters").hidden = !open;
    document.getElementById("filters-toggle").setAttribute("aria-expanded", open ? "true" : "false");
  }

  // The width hands the panel over rather than leaving it in whatever state the
  // other layout left it: wide it is simply there, narrow it starts closed so
  // the table is what the reader sees first.
  function syncFiltersHandle() {
    document.getElementById("filters-toggle").hidden = mqWide.matches;
    setFiltersOpen(mqWide.matches);
  }

  function syncSubtitle() {
    document.getElementById("app-subtitle").hidden = mqPhone.matches;
  }

  function bind() {
    document.getElementById("tabs").addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-tab]");
      if (btn) { setTab(btn.getAttribute("data-tab")); persist(); }
    });
    document.getElementById("tabs").addEventListener("keydown", function (e) {
      var tabs = Array.prototype.slice.call(document.querySelectorAll('#tabs [role="tab"]'));
      var i = tabs.indexOf(document.activeElement);
      if (i === -1) return;
      var next;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (i + 1) % tabs.length;
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = tabs.length - 1;
      else return;
      e.preventDefault();
      tabs[next].focus();
      setTab(tabs[next].getAttribute("data-tab"));
      persist();
    });

    document.querySelectorAll(".lang-toggle button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.lang = btn.getAttribute("data-lang");
        localStorage.setItem("shpato-lang", state.lang);
        renderStatic(); renderFacets(); renderResults();
        if (state.tab === "stats") renderStats();
        if (state.tab === "notes") { renderNotes(); }
        renderDrawerStatic();
        persist();
      });
    });

    document.getElementById("theme-toggle").addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-theme]");
      if (btn) { applyTheme(btn.getAttribute("data-theme")); renderStatic(); }
    });

    var search = document.getElementById("search");
    search.value = state.query;
    search.addEventListener("input", function () { state.query = search.value; refreshResults(); });

    document.getElementById("show-duplicates").checked = state.showDuplicates;
    document.getElementById("show-duplicates").addEventListener("change", function (e) {
      state.showDuplicates = e.target.checked; update();
    });

    document.getElementById("only-video").checked = state.onlyVideo;
    document.getElementById("only-video").addEventListener("change", function (e) {
      state.onlyVideo = e.target.checked; refreshResults();
    });
    document.getElementById("player-close").addEventListener("click", stopPlayer);

    document.getElementById("clear-filters").addEventListener("click", function () {
      state.categories.clear(); state.collections.clear();
      state.composers.clear(); state.performers.clear();
      state.durMin = DATA_MIN; state.durMax = DATA_MAX; state.query = "";
      document.getElementById("search").value = "";
      update();
    });

    document.getElementById("filters-toggle").addEventListener("click", function () {
      setFiltersOpen(document.getElementById("filters").hidden);
    });
    mqWide.addEventListener("change", syncFiltersHandle);
    mqPhone.addEventListener("change", syncSubtitle);

    var exportBtn = document.getElementById("export-btn");
    exportBtn.addEventListener("click", toggleExportMenu);
    document.getElementById("export-menu").addEventListener("click", function (e) {
      var item = e.target.closest("[data-export]");
      if (!item) return;
      closeExportMenu();
      exportBtn.focus();
      if (item.getAttribute("data-export") === "csv") exportCSV();
      else exportJSON();
    });
    document.addEventListener("click", function (e) {
      if (!e.target.closest(".export")) closeExportMenu();
    });
    exportBtn.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (document.getElementById("export-menu").hidden) toggleExportMenu();
      }
    });
    document.getElementById("export-menu").addEventListener("keydown", function (e) {
      var items = Array.prototype.slice.call(document.getElementById("export-menu").querySelectorAll('[role="menuitem"]'));
      var i = items.indexOf(document.activeElement);
      if (i === -1) return;
      var next;
      if (e.key === "ArrowDown") next = (i + 1) % items.length;
      else if (e.key === "ArrowUp") next = (i - 1 + items.length) % items.length;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = items.length - 1;
      else return;
      e.preventDefault();
      items[next].focus();
    });
    document.querySelector(".export").addEventListener("focusout", function (e) {
      if (!e.relatedTarget || !e.currentTarget.contains(e.relatedTarget)) closeExportMenu();
    });

    document.querySelectorAll("th.sortable").forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-sort");
        if (state.sort.key === key) state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
        else { state.sort.key = key; state.sort.dir = "asc"; }
        renderStatic(); refreshResults();
      });
    });

    document.getElementById("catalog-body").addEventListener("click", function (e) {
      // The play button lives inside the row, so it has to win over the row's
      // own handler, which opens the drawer.
      var play = e.target.closest(".row-play");
      if (play) { playRecord(play.getAttribute("data-play")); return; }
      var tr = e.target.closest("tr[data-id]");
      if (tr) selectRecord(tr.getAttribute("data-id"));
    });
    document.getElementById("note-body").addEventListener("click", function (e) {
      var tr = e.target.closest("tr[data-id]");
      if (tr) selectRecord(tr.getAttribute("data-id"));
    });

    document.getElementById("drawer").addEventListener("click", function (e) {
      if (e.target.closest("[data-close]")) { state.selected = null; renderDrawer(); }
    });
    document.getElementById("drawer").addEventListener("keydown", function (e) {
      if (e.key !== "Tab") return;
      var focusables = document.getElementById("drawer").querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (!focusables.length) return;
      var first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (state.selected) { state.selected = null; renderDrawer(); return; }
      var menu = document.getElementById("export-menu");
      if (menu && !menu.hidden) { closeExportMenu(); exportBtn.focus(); }
    });

    document.getElementById("note-severity").addEventListener("change", function (e) {
      state.noteSeverity = e.target.value; state.noteLimit = 60; renderNotes();
    });
    document.getElementById("note-rule").addEventListener("change", function (e) {
      state.noteRule = e.target.value; state.noteLimit = 60; renderNotes();
    });
    document.getElementById("note-more").addEventListener("click", function (e) {
      if (e.target.closest("#note-show-all")) { state.noteLimit = Infinity; renderNotes(); }
    });
  }

  function renderDrawerStatic() { if (state.selected) renderDrawer(); }

  syncThemeColor();
  deserialize();
  syncFiltersHandle();
  syncSubtitle();
  renderStatic();
  bind();
  setTab(state.tab);
  update();
})();
