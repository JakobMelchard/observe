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
  function submitFeedback(message, context) {
    _fetch("/__observe__/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: message,
        timestamp: new Date().toISOString(),
        context: Object.assign(enrich(), context || {}),
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

  // 7. feedback trigger button
  //
  // The shim is injected into <head>, so it runs before <body> exists.
  // Everything that touches the DOM waits for it.
  function whenReady(fn) {
    if (document.body) { fn(); return; }
    document.addEventListener("DOMContentLoaded", fn, { once: true });
  }

  whenReady(function () {
    var btn = document.createElement("button");
    btn.textContent = feedbackLabel;
    btn.style.cssText =
      "position:fixed;bottom:1rem;right:1rem;z-index:99999;opacity:0;" +
      "transition:opacity 0.2s;padding:0.5rem 1rem;border:1px solid #888;" +
      "border-radius:4px;background:#fff;cursor:pointer;font-size:0.875rem;";
    btn.onmouseenter = function () { btn.style.opacity = "1"; };
    document.body.addEventListener("mouseleave", function () {
      btn.style.opacity = "0";
    });
    btn.onclick = function () {
      var msg = prompt("Your feedback:");
      if (msg) submitFeedback(msg);
    };
    document.body.appendChild(btn);
  });
})(window.__OBSERVE_CONFIG__);
