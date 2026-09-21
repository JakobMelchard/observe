(function (cfg) {
  cfg = cfg || {};
  var endpoint = cfg.endpoint || "/__observe__/otlp";
  var feedbackLabel = cfg.feedbackLabel || "Feedback";
  var enrichHook = cfg.enrichHook || "__observe_enrich__";
  var registerSw = cfg.registerSw !== false;

  function enrich() {
    var fn = window[enrichHook];
    return (typeof fn === "function") ? fn() : {};
  }

  // 2. fetch wrapper — breadcrumb non-2xx, capture network errors
  var _fetch = window.fetch;
  window.fetch = function () {
    var args = arguments;
    if (!args[0] || (typeof args[0] === "string" && args[0].indexOf("/__observe__/") === 0)) {
      return _fetch.apply(this, args);
    }
    var start = Date.now();
    return _fetch.apply(this, args).then(function (resp) {
      if (!resp.ok) {
        tryToSendSpan("fetch error", "warning", {
          url: typeof args[0] === "string" ? args[0] : args[0].url,
          status: resp.status,
          duration: Date.now() - start,
        });
      }
      return resp;
    }).catch(function (err) {
      tryToSendSpan("fetch failed", "error", {
        url: typeof args[0] === "string" ? args[0] : args[0].url,
        error: err.message,
        duration: Date.now() - start,
      });
      throw err;
    });
  };

  // 3. global errors
  window.onerror = function (msg, source, line, col, err) {
    tryToSendSpan("uncaught error", "error", {
      message: msg,
      source: source,
      line: line,
      col: col,
      stack: err && err.stack ? err.stack : null,
    });
  };

  window.addEventListener("unhandledrejection", function (e) {
    tryToSendSpan("unhandled rejection", "error", {
      reason: e.reason && e.reason.message ? e.reason.message : String(e.reason),
      stack: e.reason && e.reason.stack ? e.reason.stack : null,
    });
  });

  // 4. feedback submission
  function submitFeedback(message, context, user) {
    return _fetch("/__observe__/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: message,
        timestamp: new Date().toISOString(),
        context: Object.assign(enrich(), context || {}),
        user: user || {},
      }),
    });
  }

  function tryToSendSpan(name, level, attrs) {
    var enriched = Object.assign(enrich(), attrs || {});
    _fetch(endpoint + "/v1/traces", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resourceSpans: [{
          resource: {},
          scopeSpans: [{
            scope: {},
            spans: [{
              name: name,
              traceId: generateId(32),
              spanId: generateId(16),
              startTimeUnixNano: Date.now() * 1e6,
              endTimeUnixNano: Date.now() * 1e6,
              attributes: Object.keys(enriched).map(function (k) {
                return { key: k, value: { stringValue: String(enriched[k]) } };
              }),
            }],
          }],
        }],
      }),
    });
  }

  function generateId(len) {
    var hex = "0123456789abcdef";
    var id = "";
    for (var i = 0; i < len; i++) id += hex[Math.floor(Math.random() * 16)];
    return id;
  }

  // 6. service worker registration
  if (registerSw && "serviceWorker" in navigator) {
    navigator.serviceWorker.register("/__observe__/observe.sw.js", { scope: "/" }).catch(function () {});
  }

  // 7. feedback trigger and form
  //
  // The shim is injected into <head>, so it runs before <body> exists.
  // Everything that touches the DOM waits for it.
  function whenReady(fn) {
    if (document.body) { fn(); return; }
    document.addEventListener("DOMContentLoaded", fn, { once: true });
  }

  // A category is worth asking for: it is the one thing a router cannot
  // infer reliably from the message text.
  var CATEGORIES = ["bug", "idea", "question"];
  var NAME_KEY = "__observe_name__";

  function remembered() {
    try { return localStorage.getItem(NAME_KEY) || ""; } catch (e) { return ""; }
  }

  function remember(name) {
    try { localStorage.setItem(NAME_KEY, name); } catch (e) { /* private window */ }
  }

  function make(tag, css, props) {
    var el = document.createElement(tag);
    el.style.cssText = css;
    for (var key in props) { if (props.hasOwnProperty(key)) el[key] = props[key]; }
    return el;
  }

  whenReady(function () {
    var dark = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
    var bg = dark ? "#1f1f24" : "#ffffff";
    var fg = dark ? "#e8e8e4" : "#111111";
    var line = dark ? "#44444c" : "#888888";
    var anchor = "position:fixed;bottom:1rem;right:1rem;z-index:99999;";
    var field =
      "width:100%;box-sizing:border-box;margin:0 0 0.5rem;padding:0.35rem 0.5rem;" +
      "border:1px solid " + line + ";border-radius:4px;background:" + bg + ";color:" + fg + ";" +
      "font:inherit;";

    var btn = make("button", anchor +
      "opacity:0;transition:opacity 0.2s;padding:0.5rem 1rem;border:1px solid " + line + ";" +
      "border-radius:4px;background:" + bg + ";color:" + fg + ";cursor:pointer;font-size:0.875rem;",
      { textContent: feedbackLabel, type: "button" });
    btn.onmouseenter = function () { btn.style.opacity = "1"; };
    btn.onfocus = function () { btn.style.opacity = "1"; };
    document.body.addEventListener("mouseleave", function () {
      if (panel.style.display === "none") btn.style.opacity = "0";
    });

    var panel = make("div", anchor +
      "display:none;width:20rem;max-width:calc(100vw - 2rem);padding:0.75rem;" +
      "border:1px solid " + line + ";border-radius:6px;background:" + bg + ";color:" + fg + ";" +
      "font:0.875rem/1.4 system-ui,-apple-system,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,0.25);",
      { role: "dialog" });
    panel.setAttribute("aria-label", feedbackLabel);

    var category = make("select", field);
    for (var i = 0; i < CATEGORIES.length; i++) {
      category.appendChild(make("option", "", { value: CATEGORIES[i], textContent: CATEGORIES[i] }));
    }
    var message = make("textarea", field + "height:5rem;resize:vertical;",
      { placeholder: "What happened?", spellcheck: false });
    var name = make("input", field,
      { type: "text", placeholder: "Your name (optional)", value: remembered() });

    var status = make("span", "flex:1;opacity:0.7;");
    var cancel = make("button", "padding:0.35rem 0.7rem;border:1px solid " + line + ";" +
      "border-radius:4px;background:none;color:" + fg + ";cursor:pointer;font:inherit;",
      { textContent: "Cancel", type: "button" });
    var send = make("button", "padding:0.35rem 0.7rem;border:1px solid " + line + ";" +
      "border-radius:4px;background:" + fg + ";color:" + bg + ";cursor:pointer;font:inherit;",
      { textContent: "Send", type: "button" });

    var row = make("div", "display:flex;gap:0.5rem;align-items:center;");
    row.appendChild(status);
    row.appendChild(cancel);
    row.appendChild(send);

    panel.appendChild(make("label", "display:block;margin:0 0 0.25rem;opacity:0.7;",
      { textContent: feedbackLabel }));
    panel.appendChild(category);
    panel.appendChild(message);
    panel.appendChild(name);
    panel.appendChild(row);

    function open() {
      panel.style.display = "block";
      btn.style.display = "none";
      status.textContent = "";
      message.focus();
    }

    function close() {
      panel.style.display = "none";
      btn.style.display = "";
      btn.style.opacity = "0";
      message.value = "";
    }

    function submit() {
      var text = message.value.trim();
      if (!text) { message.focus(); return; }
      var who = name.value.trim();
      if (who) remember(who);
      send.disabled = true;
      status.textContent = "Sending…";
      submitFeedback(text, {}, { category: category.value, name: who }).then(
        function (resp) {
          send.disabled = false;
          if (resp && !resp.ok) { status.textContent = "Could not send."; return; }
          status.textContent = "Thanks.";
          setTimeout(close, 900);
        },
        function () { send.disabled = false; status.textContent = "Could not send."; }
      );
    }

    btn.onclick = open;
    cancel.onclick = close;
    send.onclick = submit;
    panel.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { close(); return; }
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
    });

    document.body.appendChild(btn);
    document.body.appendChild(panel);
  });
})(window.__OBSERVE_CONFIG__);
