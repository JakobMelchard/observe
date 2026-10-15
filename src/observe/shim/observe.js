/** @param {ObserveWindow} win */ (function (win) {
  var cfg = win.__OBSERVE_CONFIG__ || {};
  var endpoint = cfg.endpoint || "/__observe__/otlp";
  // A static site has no middleware behind it: feedback can go to a remote receiver with a
  // bearer token, and the OTLP spans can be switched off when nothing collects them.
  var feedbackEndpoint = cfg.feedbackEndpoint || "/__observe__/feedback";
  var token = cfg.token || "";
  var traces = cfg.traces !== false;
  var feedbackLabel = cfg.feedbackLabel || "Feedback";
  var enrichHook = cfg.enrichHook || "__observe_enrich__";
  var registerSw = cfg.registerSw === true;

  /** @returns {Record<string, unknown>} what the page's enrich hook returns, or nothing */
  function enrich() {
    var fn = win[enrichHook];
    return typeof fn === "function" ? fn() : {};
  }

  var _fetch = window.fetch;
  /** @type {typeof fetch} */
  window.fetch = function () {
    var args = /** @type {Parameters<typeof fetch>} */ (/** @type {unknown} */ (arguments));
    var input = /** @type {Partial<Request> | undefined} */ (args[0]);
    // string, Request (.url) or URL (String() is its href)
    var url = input && input.url ? input.url : String(input || "");
    if (!url || url.indexOf("/__observe__/") === 0 || url === feedbackEndpoint) {
      return _fetch.apply(this, args);
    }
    var start = Date.now();
    return _fetch
      .apply(this, args)
      .then(function (resp) {
        if (!resp.ok) {
          tryToSendSpan("fetch error", "warning", {
            url: url,
            status: resp.status,
            duration: Date.now() - start,
          });
        }
        return resp;
      })
      .catch(function (err) {
        tryToSendSpan("fetch failed", "error", {
          url: url,
          error: err.message,
          duration: Date.now() - start,
        });
        throw err;
      });
  };

  // A listener, not window.onerror: the host page may have its own handler there.
  window.addEventListener("error", function (e) {
    tryToSendSpan("uncaught error", "error", {
      message: e.message,
      source: e.filename,
      line: e.lineno,
      col: e.colno,
      stack: e.error && e.error.stack ? e.error.stack : null,
    });
  });

  window.addEventListener("unhandledrejection", function (e) {
    tryToSendSpan("unhandled rejection", "error", {
      reason: e.reason && e.reason.message ? e.reason.message : String(e.reason),
      stack: e.reason && e.reason.stack ? e.reason.stack : null,
    });
  });

  /**
   * @param {string} message what the user wrote
   * @param {Record<string, unknown>} [context] merged over the enrich hook's result
   * @param {Record<string, unknown>} [user] who sent it and the category
   * @returns {Promise<Response>} the receiver's answer
   */
  function submitFeedback(message, context, user) {
    /** @type {Record<string, string>} */
    var headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = "Bearer " + token;
    return _fetch(feedbackEndpoint, {
      method: "POST",
      headers: headers,
      body: JSON.stringify({
        repo: cfg.repo,
        message: message,
        timestamp: new Date().toISOString(),
        context: Object.assign(enrich(), context || {}),
        user: user || {},
      }),
    });
  }

  /**
   * Sends one OTLP span; a failed send is dropped.
   *
   * @param {string} name span name
   * @param {string} level error, warning or info
   * @param {Record<string, unknown>} [attrs] span attributes, stringified
   */
  function tryToSendSpan(name, level, attrs) {
    if (!traces) return;
    /** @type {Record<string, unknown>} */
    var enriched = Object.assign(enrich(), attrs || {}, { level: level });
    _fetch(endpoint + "/v1/traces", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceSpans: [
          {
            resource: {},
            scopeSpans: [
              {
                scope: {},
                spans: [
                  {
                    name: name,
                    traceId: generateId(32),
                    spanId: generateId(16),
                    startTimeUnixNano: Date.now() * 1e6,
                    endTimeUnixNano: Date.now() * 1e6,
                    attributes: Object.keys(enriched).map(function (k) {
                      return { key: k, value: { stringValue: String(enriched[k]) } };
                    }),
                  },
                ],
              },
            ],
          },
        ],
      }),
    }).catch(function () {
      // Left unhandled, a failed send would come back as an "unhandled rejection" span,
      // which fails too: a loop for as long as the endpoint is down.
    });
  }

  /**
   * @param {number} len number of hex digits
   * @returns {string} a random hex id
   */
  function generateId(len) {
    var hex = "0123456789abcdef";
    var id = "";
    var i;
    for (i = 0; i < len; i++) id += hex[Math.floor(Math.random() * 16)];
    return id;
  }

  if (registerSw && "serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/__observe__/observe.sw.js", { scope: "/" })
      .catch(function (err) {
        console.warn("observe: service worker registration failed", err);
      });
  }

  // The shim is injected into <head>, so it runs before <body> exists.
  // Everything that touches the DOM waits for it.
  /** @param {() => void} fn runs once document.body exists */
  function whenReady(fn) {
    if (document.body) {
      fn();
      return;
    }
    document.addEventListener("DOMContentLoaded", fn, { once: true });
  }

  // A category is worth asking for: it is the one thing a router cannot
  // infer reliably from the message text.
  var CATEGORIES = ["bug", "idea", "question"];
  var NAME_KEY = "__observe_name__";

  /** @returns {string} the name the user gave last time */
  function remembered() {
    try {
      return localStorage.getItem(NAME_KEY) || "";
    } catch (_e) {
      return "";
    }
  }

  /** @param {string} name kept for the next report */
  function remember(name) {
    try {
      localStorage.setItem(NAME_KEY, name);
    } catch (_e) {
      /* private window */
    }
  }

  // One stylesheet on the org token variables, so a page that loads tokens.css themes the form.
  // The fallbacks are the dark tokens.
  var CSS = [
    ".observe-btn, .observe-panel { position: fixed; bottom: 1rem; right: 1rem; z-index: 99999;",
    "  border: 1px solid var(--line, rgba(98, 114, 164, 0.25)); border-radius: 6px;",
    "  background: var(--card, #15171f); color: var(--fg, #f8f8f2);",
    "  font: 0.875rem/1.4 var(--font-sans, Satoshi, sans-serif); }",
    // Always visible: a trigger that only shows on hover is never found on a desktop and
    // never shown on a touch screen.
    ".observe-btn { padding: 0.5rem 1rem; cursor: pointer; }",
    ".observe-panel { display: none; width: 20rem; max-width: calc(100vw - 2rem); padding: 0.75rem;",
    "  box-shadow: var(--shadow-overlay, 0 16px 64px rgba(0, 0, 0, 0.5)); }",
    ".observe-panel label { display: block; margin: 0 0 0.25rem; color: var(--muted, #6272a4); }",
    ".observe-panel select, .observe-panel textarea, .observe-panel input { width: 100%;",
    "  box-sizing: border-box; margin: 0 0 0.5rem; padding: 0.35rem 0.5rem;",
    "  border: 1px solid var(--line, rgba(98, 114, 164, 0.25)); border-radius: 4px;",
    "  background: var(--bg, #0b0d10); color: var(--fg, #f8f8f2); font: inherit; }",
    ".observe-panel textarea { height: 5rem; resize: vertical; }",
    ".observe-row { display: flex; gap: 0.5rem; align-items: center; }",
    ".observe-row span { flex: 1; color: var(--muted, #6272a4); }",
    ".observe-row button { padding: 0.35rem 0.7rem; border: 1px solid var(--line, rgba(98, 114, 164, 0.25));",
    "  border-radius: 4px; background: none; color: var(--fg, #f8f8f2); cursor: pointer; font: inherit; }",
    ".observe-row .observe-send { background: var(--fg, #f8f8f2); color: var(--bg, #0b0d10); }",
  ].join("\n");

  // A constructed sheet is not inline style, so a CSP without 'unsafe-inline' lets it through.
  /** Adds the form's stylesheet to the page. */
  function addStyles() {
    var sheet = document.adoptedStyleSheets && window.CSSStyleSheet ? new CSSStyleSheet() : null;
    if (sheet) {
      sheet.replaceSync(CSS);
      document.adoptedStyleSheets = document.adoptedStyleSheets.concat(sheet);
      return;
    }
    var style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  /**
   * @template {keyof HTMLElementTagNameMap} K
   * @param {K} tag element name
   * @param {string} [cls] class name
   * @param {Partial<HTMLElementTagNameMap[K]>} [props] properties assigned to the element
   * @returns {HTMLElementTagNameMap[K]} the new element
   */
  function make(tag, cls, props) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    Object.assign(el, props);
    return el;
  }

  whenReady(function () {
    addStyles();

    // A site with its own button (cfg.button === false) gets none and calls window.__observe__.open().
    var btn = make("button", "observe-btn", { textContent: feedbackLabel, type: "button" });

    var panel = make("div", "observe-panel", { role: "dialog" });
    panel.setAttribute("aria-label", feedbackLabel);

    var category = make("select");
    CATEGORIES.forEach(function (c) {
      category.appendChild(make("option", "", { value: c, textContent: c }));
    });
    var message = make("textarea", "", { placeholder: "What happened?", spellcheck: false });
    var name = make("input", "", {
      type: "text",
      placeholder: "Your name (optional)",
      value: remembered(),
    });

    var status = make("span");
    var cancel = make("button", "", { textContent: "Cancel", type: "button" });
    var send = make("button", "observe-send", { textContent: "Send", type: "button" });

    var row = make("div", "observe-row");
    row.appendChild(status);
    row.appendChild(cancel);
    row.appendChild(send);

    panel.appendChild(make("label", "", { textContent: feedbackLabel }));
    panel.appendChild(category);
    panel.appendChild(message);
    panel.appendChild(name);
    panel.appendChild(row);

    /** Shows the form and hides the button. */
    function open() {
      panel.style.display = "block";
      btn.style.display = "none";
      status.textContent = "";
      message.focus();
    }

    /** Hides the form, shows the button and clears the message. */
    function close() {
      panel.style.display = "";
      btn.style.display = "";
      message.value = "";
    }

    /** Sends the form; an empty message only refocuses it. */
    function submit() {
      var text = message.value.trim();
      if (!text) {
        message.focus();
        return;
      }
      var who = name.value.trim();
      if (who) remember(who);
      send.disabled = true;
      status.textContent = "Sending…";
      submitFeedback(text, {}, { category: category.value, name: who }).then(
        function (resp) {
          send.disabled = false;
          if (resp && !resp.ok) {
            status.textContent = "Could not send.";
            return;
          }
          status.textContent = "Thanks.";
          setTimeout(close, 900);
        },
        function () {
          send.disabled = false;
          status.textContent = "Could not send.";
        },
      );
    }

    btn.onclick = open;
    cancel.onclick = close;
    send.onclick = submit;
    panel.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        close();
        return;
      }
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
    });

    if (cfg.button !== false) document.body.appendChild(btn);
    document.body.appendChild(panel);
    win.__observe__ = { open: open, close: close };
  });
})(/** @type {ObserveWindow} */ (/** @type {unknown} */ (window)));

// Types sit after the IIFE: a JSDoc block in front of it would be read twice.

/**
 * Set by the middleware (or a static page) as window.__OBSERVE_CONFIG__ before the shim runs.
 *
 * @typedef {object} ObserveConfig
 * @property {string} [repo] repo the feedback is filed against
 * @property {string} [endpoint] OTLP base URL
 * @property {string} [feedbackEndpoint] feedback receiver URL
 * @property {string} [token] bearer token for a remote feedback receiver
 * @property {boolean} [traces] false switches the OTLP spans off
 * @property {string} [feedbackLabel] button and dialog label
 * @property {string} [enrichHook] name of a window function whose result is merged into every report
 * @property {boolean} [registerSw] true registers observe.sw.js
 * @property {boolean} [button] false leaves the button out; the site calls window.__observe__.open()
 */

/**
 * @typedef {Window & Record<string, unknown> & {
 *   __OBSERVE_CONFIG__?: ObserveConfig,
 *   __observe__?: { open: () => void, close: () => void },
 * }} ObserveWindow
 */
