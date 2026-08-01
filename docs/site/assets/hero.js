/* The hero's three examples, and the prompt that hands one to an agent.
 *
 * Two independent pieces, both scoped to the hero:
 *
 *   1. A plain ARIA tablist over the code panels. Panels 2 and 3 carry the
 *      `hidden` attribute in the markup rather than being hidden from here, so
 *      a visitor without JavaScript sees exactly what the page showed before
 *      the tabs existed: the single-point example, no empty chrome.
 *
 *   2. The prompt box. It does not run anything; it wraps the question in the
 *      framing an agent needs (what QPUBench is, which schemas to use, where
 *      to persist) and either copies that or opens it in Cebule, the same
 *      hand-off mqs.dk makes.
 */
(function () {
  "use strict";

  /* ---------- tabs ---------- */

  var tablist = document.querySelector(".code-tabs");

  if (tablist) {
    var tabs = [].slice.call(tablist.querySelectorAll('[role="tab"]'));

    var select = function (tab, moveFocus) {
      tabs.forEach(function (other) {
        var chosen = other === tab;
        other.setAttribute("aria-selected", chosen ? "true" : "false");
        other.tabIndex = chosen ? 0 : -1;

        var panel = document.getElementById(other.getAttribute("aria-controls"));
        if (panel) panel.hidden = !chosen;
      });
      if (moveFocus) tab.focus();
    };

    tablist.addEventListener("click", function (event) {
      var tab = event.target.closest('[role="tab"]');
      if (tab) select(tab, false);
    });

    // Arrow keys move between tabs; that is what a tablist is expected to do,
    // and without it the roving tabindex above would trap keyboard users.
    tablist.addEventListener("keydown", function (event) {
      var index = tabs.indexOf(document.activeElement);
      if (index < 0) return;

      var next = null;
      if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
      else if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
      else if (event.key === "Home") next = tabs[0];
      else if (event.key === "End") next = tabs[tabs.length - 1];

      if (next) {
        event.preventDefault();
        select(next, true);
      }
    });
  }

  /* ---------- prompt ---------- */

  var form = document.getElementById("prompt-form");
  if (!form) return;

  var input = document.getElementById("prompt-input");
  var status = document.getElementById("prompt-status");
  var copyButton = document.getElementById("prompt-copy");

  var FRAMING =
    "You have the QPUBench framework available (pip install qpubench); the " +
    "documentation is at https://qpubench.org.\n\n" +
    "Set the study up with QPUBench's own schemas (CircuitSpec, BackendSpec, " +
    "ExecutionOptions, QuantumResult) and drive it with a BenchmarkRunner " +
    "that persists every record, so every result lands in one comparable " +
    "format. Use runner.sweep() if the study is more than a single point.\n\n";

  var DEFAULT_BACKEND =
    "\n\nNo backend was named, so run this on the Qiskit Aer simulator " +
    "(qpubench.backends.AerAdapter).";

  /* Names that count as "the backend is decided". Kept deliberately literal:
   * guessing wrong and appending the Aer line to a study that already names a
   * QPU would contradict the question, which is worse than leaving it off. */
  var NAMED_BACKEND = new RegExp(
    "\\b(" +
      "aer|qiskit|ibm|ibmq|torino|brisbane|braket|iqm|quantinuum|honeywell|" +
      "qibo|quest|pennylane|lightning|qrack|quera|aquila|bloqade|orca|xanadu|" +
      "borealis|rigetti|ionq|pasqal|oqc|classiq|cebule|qcloud|dtu|" +
      "simulator|statevector|emulator|hardware|qpu" +
    ")\\b",
    "i"
  );

  var buildPrompt = function (question) {
    return FRAMING + "Task: " + question +
      (NAMED_BACKEND.test(question) ? "" : DEFAULT_BACKEND);
  };

  var timer = null;
  var say = function (message) {
    if (!status) return;
    status.textContent = message;
    window.clearTimeout(timer);
    if (message) timer = window.setTimeout(function () { status.textContent = ""; }, 4000);
  };

  var question = function () {
    var text = input.value.trim();
    if (!text) {
      input.focus();
      say("Type a question first.");
    }
    return text;
  };

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = question();
    if (!text) return;
    window.open("https://cebule.io?prompt=" + encodeURIComponent(buildPrompt(text)), "_blank",
                "noopener");
  });

  // Enter submits, Shift+Enter keeps the newline: a textarea so the long
  // example questions stay readable, but it still behaves like a prompt box.
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (form.requestSubmit) form.requestSubmit();
      else form.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  if (copyButton) {
    copyButton.addEventListener("click", function () {
      var text = question();
      if (!text) return;
      var prompt = buildPrompt(text);

      var fallback = function () {
        // Clipboard API is unavailable outside a secure context, and denied in
        // some browsers. Selecting the text at least leaves the visitor one
        // keystroke away rather than with a button that silently did nothing.
        input.value = prompt;
        input.select();
        var copied = false;
        try {
          copied = document.execCommand("copy");
        } catch (e) {
          copied = false;
        }
        say(copied ? "Copied." : "Press Ctrl/⌘+C to copy.");
      };

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(prompt).then(function () {
          say("Copied.");
        }, fallback);
      } else {
        fallback();
      }
    });
  }

  document.addEventListener("click", function (event) {
    var suggestion = event.target.closest && event.target.closest(".prompt-suggestion");
    if (!suggestion) return;
    input.value = suggestion.textContent.trim();
    input.focus();
    say("");
  });
})();
