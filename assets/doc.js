/* The static catalogue page's behaviour.

   The page itself needs no script: every work is in the HTML, so a crawler and
   a reader with scripting off have the catalogue. This file carries only the
   controls that cannot be markup — the theme switch, the share intents, and the
   cue that a table can be panned sideways — because they are the app's, and the
   page should behave like the app's. */

(function () {
  "use strict";

  // The browser chrome colour lives in the palette as --theme-color, so it
  // cannot drift from the canvas it is meant to match. Same rule as app.js.
  function syncThemeColor() {
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) return;
    var c = getComputedStyle(document.documentElement).getPropertyValue("--theme-color").trim();
    if (c) meta.setAttribute("content", c);
  }

  // The theme itself is applied before first paint by the inline script in the
  // head; this is the state the two buttons report, and the browser chrome.
  function syncTheme() {
    var theme = document.documentElement.getAttribute("data-theme") || "light";
    document.querySelectorAll(".theme-toggle button").forEach(function (btn) {
      btn.setAttribute("aria-pressed", btn.getAttribute("data-theme") === theme ? "true" : "false");
    });
    syncThemeColor();
  }

  var toggle = document.querySelector(".theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-theme]");
      if (!btn) return;
      var theme = btn.getAttribute("data-theme");
      document.documentElement.setAttribute("data-theme", theme);
      try { localStorage.setItem("shpato-theme", theme); } catch (err) {}
      syncTheme();
    });
  }

  // Share intents point at this page's canonical address rather than at
  // location.href: opened from disk, a file: URL would mean nothing to whoever
  // received it. The same four, and the same rule, as the app's footer.
  function syncShareLinks() {
    var canonical = document.querySelector('link[rel="canonical"]');
    var url = (canonical && canonical.href) || location.href;
    var u = encodeURIComponent(url);
    var title = document.title;
    var hrefs = {
      // x.com still serves the classic intent path, and it redirects either way.
      "share-x": "https://twitter.com/intent/tweet?text=" + encodeURIComponent(title) + "&url=" + u,
      "share-facebook": "https://www.facebook.com/sharer/sharer.php?u=" + u,
      "share-linkedin": "https://www.linkedin.com/sharing/share-offsite/?url=" + u,
      // Bluesky has no separate url parameter: it has to be in the text.
      "share-bluesky": "https://bsky.app/intent/compose?text=" + encodeURIComponent(title + " " + url)
    };
    Object.keys(hrefs).forEach(function (id) {
      var link = document.getElementById(id);
      if (link) link.href = hrefs[id];
    });
  }

  // The cue is a layer above the card (see .table-frame), so it cannot read the
  // scroll position itself: the frame carries which sides still have table left
  // and the stylesheet shows the gradients. Same rule as app.js.
  function syncPanCue(wrap) {
    var frame = wrap.closest(".table-frame");
    if (!frame) return;
    var max = wrap.scrollWidth - wrap.clientWidth;
    var sides = [];
    if (max > 1) {
      if (wrap.scrollLeft > 0) sides.push("left");
      if (wrap.scrollLeft < max - 1) sides.push("right");
    }
    if (sides.length) frame.setAttribute("data-pan", sides.join(" "));
    else frame.removeAttribute("data-pan");
  }

  function syncPanCues() {
    document.querySelectorAll(".table-frame > .table-wrap").forEach(syncPanCue);
  }

  document.querySelectorAll(".table-frame > .table-wrap").forEach(function (wrap) {
    wrap.addEventListener("scroll", function () { syncPanCue(wrap); }, { passive: true });
  });
  window.addEventListener("resize", syncPanCues);
  // How wide the table is comes from the font, which can land after the parser
  // is done, so what can be panned is not settled until it has. Same rule as
  // the app's boot.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(syncPanCues);

  syncTheme();
  syncShareLinks();
  syncPanCues();
})();
