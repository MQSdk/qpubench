/* Day / night switch, matching the one on mqs.dk.
 *
 * The *initial* theme is set by a short inline script in the <head> of every
 * page, before first paint, so there is no flash of the wrong palette. This
 * file only wires up the button and keeps the choice.
 *
 * Precedence: stored choice → OS preference → dark (mqs.dk is dark-first).
 */
(function () {
  "use strict";

  var KEY = "qpubench-theme-mode";
  var root = document.documentElement;

  function read() {
    try {
      var stored = localStorage.getItem(KEY);
      return stored === "light" || stored === "dark" ? stored : null;
    } catch (e) {
      return null;
    }
  }

  function systemMode() {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function apply(mode) {
    root.setAttribute("data-theme", mode);

    // Keep the mobile browser chrome in step with the page.
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", mode === "dark" ? "#22043B" : "#F9F9F9");

    var buttons = document.querySelectorAll(".theme-toggle");
    for (var i = 0; i < buttons.length; i++) {
      var next = mode === "dark" ? "day" : "night";
      buttons[i].setAttribute("aria-label", "Switch to " + next + " view");
      buttons[i].setAttribute("title", "Switch to " + next + " view");
    }
  }

  apply(read() || systemMode());

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest(".theme-toggle");
    if (!button) return;
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    apply(next);
    try {
      localStorage.setItem(KEY, next);
    } catch (e) {
      /* private mode — the choice just will not survive the page. */
    }
  });

  // Until a choice is made, follow the OS if the visitor changes it mid-visit.
  var query = window.matchMedia("(prefers-color-scheme: light)");
  var onChange = function () {
    if (!read()) apply(systemMode());
  };
  if (query.addEventListener) query.addEventListener("change", onChange);
  else if (query.addListener) query.addListener(onChange);
})();
