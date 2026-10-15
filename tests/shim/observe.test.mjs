// Node tests for the browser shim. No browser: the shim runs in a vm context
// against a fake window, and `fetch` stands in for the network.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../../src/observe/shim/observe.js", import.meta.url), "utf8");

/** @typedef {(e: Record<string, unknown>) => void} Listener */

/**
 * Runs the shim against a fake window.
 *
 * @param {(...args: unknown[]) => Promise<unknown>} fetch stands in for the network
 * @param {Record<string, unknown>} [extra] window properties to add or replace
 */
function load(fetch, extra) {
  /** @type {Record<string, Listener[]>} */
  const listeners = {};
  /** @type {Record<string, unknown> & { fetch: (input: unknown) => Promise<unknown> }} */
  const window = Object.assign(
    {
      __OBSERVE_CONFIG__: { registerSw: false },
      fetch: fetch,
      navigator: {},
      console: console,
      // No body yet, so the feedback form never builds.
      document: { body: null, addEventListener() {} },
      /**
       * @param {string} type event name
       * @param {Listener} fn handler
       */
      addEventListener(type, fn) {
        listeners[type] = listeners[type] || [];
        listeners[type].push(fn);
      },
    },
    extra,
  );
  window.window = window;
  vm.runInNewContext(SOURCE, window);
  return { window: window, listeners: listeners };
}

/**
 * @typedef {{ key: string, value: { stringValue: string } }} Attribute
 */

/**
 * @param {IArguments[]} calls the arguments of each OTLP post
 * @returns {{ name: string, attrs: Record<string, string> }[]} the span each post carried
 */
function spans(calls) {
  return calls.map(function (call) {
    const span = JSON.parse(call[1].body).resourceSpans[0].scopeSpans[0].spans[0];
    /** @type {Record<string, string>} */
    const attrs = {};
    span.attributes.forEach(function (/** @type {Attribute} */ a) {
      attrs[a.key] = a.value.stringValue;
    });
    return { name: span.name, attrs: attrs };
  });
}

function settle() {
  return new Promise(function (resolve) {
    setTimeout(resolve, 50);
  });
}

test("a failing endpoint does not cause a resend loop", async function () {
  let calls = 0;
  const shim = load(function () {
    calls += 1;
    // With a loop, it never yields to the event loop. Stop feeding it after
    // a few rounds so the test fails instead of hanging.
    if (calls > 20) return new Promise(function () {});
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  // A browser hands every unhandled rejection back to the page.
  const report = function (/** @type {unknown} */ reason) {
    shim.listeners.unhandledrejection.forEach(function (fn) {
      fn({ reason: reason });
    });
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
  /** @type {IArguments[]} */
  const calls = [];
  const host = function () {};
  const shim = load(
    function () {
      calls.push(arguments);
      return Promise.resolve({ ok: true });
    },
    { onerror: host },
  );
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
  /** @type {IArguments[]} */
  const calls = [];
  const shim = load(function (/** @type {unknown} */ target) {
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
  load(
    function () {
      return Promise.resolve({ ok: true });
    },
    {
      __OBSERVE_CONFIG__: { registerSw: true },
      navigator: {
        serviceWorker: {
          register() {
            return Promise.reject(new Error("denied"));
          },
        },
      },
      console: {
        warn() {
          warnings.push(arguments);
        },
      },
    },
  );
  await settle();
  assert.equal(warnings.length, 1);
});

test("no service worker is registered unless registerSw is set", function () {
  let registered = 0;
  const navigator = {
    serviceWorker: {
      register() {
        registered += 1;
        return Promise.resolve();
      },
    },
  };
  load(
    function () {
      return Promise.resolve({ ok: true });
    },
    { __OBSERVE_CONFIG__: {}, navigator: navigator },
  );
  load(
    function () {
      return Promise.resolve({ ok: true });
    },
    { __OBSERVE_CONFIG__: undefined, navigator: navigator },
  );
  assert.equal(registered, 0);
});
