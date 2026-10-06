// Node tests for the browser shim. No browser: the shim runs in a vm context
// against a fake window, and `fetch` stands in for the network.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../../src/observe/shim/observe.js", import.meta.url), "utf8");

function load(fetch, extra) {
  const listeners = {};
  const window = Object.assign({
    __OBSERVE_CONFIG__: { registerSw: false },
    fetch: fetch,
    navigator: {},
    console: console,
    // No body yet, so the feedback form never builds.
    document: { body: null, addEventListener() {} },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  }, extra);
  window.window = window;
  vm.runInNewContext(SOURCE, window);
  return { window: window, listeners: listeners };
}

function spans(calls) {
  return calls.map(function (call) {
    const span = JSON.parse(call[1].body).resourceSpans[0].scopeSpans[0].spans[0];
    const attrs = {};
    span.attributes.forEach(function (a) { attrs[a.key] = a.value.stringValue; });
    return { name: span.name, attrs: attrs };
  });
}

function settle() {
  return new Promise(function (resolve) { setTimeout(resolve, 50); });
}

test("a failing endpoint does not cause a resend loop", async function () {
  let calls = 0;
  const shim = load(function () {
    calls += 1;
    // Unfixed, the loop never yields to the event loop. Stop feeding it after
    // a few rounds so the test fails instead of hanging.
    if (calls > 20) return new Promise(function () {});
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  // A browser hands every unhandled rejection back to the page.
  const report = function (reason) {
    shim.listeners.unhandledrejection.forEach(function (fn) { fn({ reason: reason }); });
  };
  process.on("unhandledRejection", report);
  try {
    report(new Error("boom"));
    await settle();
  } finally {
    process.off("unhandledRejection", report);
  }
  assert.equal(calls, 1);
});

test("the host page's onerror handler is kept and errors are still reported", function () {
  const calls = [];
  const host = function () {};
  const shim = load(function () {
    calls.push(arguments);
    return Promise.resolve({ ok: true });
  }, { onerror: host });
  assert.equal(shim.window.onerror, host);

  const err = new Error("boom");
  shim.listeners.error.forEach(function (fn) {
    fn({ message: "boom", filename: "app.js", lineno: 3, colno: 7, error: err });
  });
  const sent = spans(calls);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].name, "uncaught error");
  assert.equal(sent[0].attrs.message, "boom");
  assert.equal(sent[0].attrs.source, "app.js");
  assert.equal(sent[0].attrs.line, "3");
  assert.equal(sent[0].attrs.stack, err.stack);
});

test("a URL object passed to fetch is reported by its href", async function () {
  const calls = [];
  const shim = load(function (target) {
    if (target instanceof URL) return Promise.resolve({ ok: false, status: 500 });
    calls.push(arguments);
    return Promise.resolve({ ok: true });
  });
  await shim.window.fetch(new URL("http://app.test/api"));
  const sent = spans(calls);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].attrs.url, "http://app.test/api");
});

test("a failed service worker registration is logged", async function () {
  const warnings = [];
  load(function () { return Promise.resolve({ ok: true }); }, {
    __OBSERVE_CONFIG__: {},
    navigator: { serviceWorker: { register() { return Promise.reject(new Error("denied")); } } },
    console: { warn() { warnings.push(arguments); } },
  });
  await settle();
  assert.equal(warnings.length, 1);
});
