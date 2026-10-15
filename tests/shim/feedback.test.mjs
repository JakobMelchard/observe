// Node tests for the feedback form. The shim runs against a fake document that records what it
// builds; `fetch` stands in for the network.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../../src/observe/shim/observe.js", import.meta.url), "utf8");

/**
 * What the shim builds, as far as these tests look at it.
 *
 * @typedef {object} FakeElement
 * @property {string} tag element name
 * @property {FakeElement[]} children appended children
 * @property {{ display?: string }} style inline style the shim sets
 * @property {string} value form value
 * @property {string} textContent text
 * @property {string} className class
 * @property {boolean} [disabled] set on the send button while sending
 * @property {() => void} [onclick] set by the shim on its buttons
 * @property {(child: FakeElement) => FakeElement} appendChild appends and returns child
 * @property {() => void} setAttribute ignored
 * @property {(type: string, fn: (e: unknown) => void) => void} addEventListener records fn
 * @property {() => void} focus ignored
 */

/**
 * @typedef {{ ok: boolean, status?: number }} FakeResponse
 * @typedef {{ method: string, headers: Record<string, string>, body: string }} FetchInit
 * @typedef {(url: string, init: FetchInit) => Promise<FakeResponse>} FakeFetch
 */

/**
 * @param {string} tag element name
 * @returns {FakeElement} an element that records what is appended to it
 */
function element(tag) {
  /** @type {Record<string, (e: unknown) => void>} */
  const listeners = {};
  return {
    tag: tag,
    children: [],
    style: {},
    value: "",
    textContent: "",
    className: "",
    appendChild(child) { this.children.push(child); return child; },
    setAttribute() {},
    addEventListener(type, fn) { listeners[type] = fn; },
    focus() {},
  };
}

/**
 * @param {FakeElement} root where the search starts
 * @param {(e: FakeElement) => boolean} match the test
 * @returns {FakeElement | null} the first match, depth first
 */
function find(root, match) {
  if (match(root)) return root;
  for (const child of root.children) {
    const found = find(child, match);
    if (found) return found;
  }
  return null;
}

/**
 * @param {FakeElement} el a button the shim built
 */
function click(el) {
  assert.ok(el.onclick, "no click handler");
  el.onclick();
}

/**
 * Runs the shim against a fake page and returns the form it built.
 *
 * @param {Record<string, unknown>} config window.__OBSERVE_CONFIG__
 * @param {FakeFetch} fetch stands in for the network
 */
function load(config, fetch) {
  /** @type {Record<string, string>} */
  const stored = {};
  const body = element("body");
  /** @type {Record<string, unknown> & { __observe__?: { open(): void, close(): void } }} */
  const window = {
    __OBSERVE_CONFIG__: config,
    fetch: fetch,
    navigator: {},
    console: console,
    localStorage: {
      getItem: (/** @type {string} */ k) => stored[k] ?? null,
      setItem: (/** @type {string} */ k, /** @type {string} */ v) => { stored[k] = v; },
    },
    setTimeout() {},
    addEventListener() {},
    document: { body: body, head: element("head"), createElement: element, addEventListener() {} },
  };
  window.window = window;
  vm.runInNewContext(SOURCE, window);
  /**
   * @param {(e: FakeElement) => boolean} match the test
   * @returns {FakeElement} the element, which must exist
   */
  const get = (match) => {
    const found = find(body, match);
    assert.ok(found);
    return found;
  };
  /** @param {string} tag element name */
  const byTag = (tag) => get((e) => e.tag === tag);
  return {
    window: window,
    stored: stored,
    body: body,
    category: byTag("select"),
    message: byTag("textarea"),
    name: byTag("input"),
    send: get((e) => e.className === "observe-send"),
    status: get((e) => e.className === "observe-row").children[0],
    trigger: find(body, (e) => e.className === "observe-btn"),
    panel: get((e) => e.className === "observe-panel"),
  };
}

function settle() {
  return new Promise(function (resolve) { setTimeout(resolve, 20); });
}

test("submit sends the feedback to the endpoint with the token", async function () {
  /** @type {[string, FetchInit][]} */
  const calls = [];
  const form = load(
    { feedbackEndpoint: "https://recv.example/feedback", token: "secret", repo: "o/r" },
    function (url, init) { calls.push([url, init]); return Promise.resolve({ ok: true }); },
  );
  form.message.value = "  it broke  ";
  form.category.value = "bug";
  form.name.value = " Jo ";
  click(form.send);
  await settle();

  assert.equal(calls.length, 1);
  const [url, init] = calls[0];
  assert.equal(url, "https://recv.example/feedback");
  assert.equal(init.method, "POST");
  assert.equal(init.headers.Authorization, "Bearer secret");
  const sent = JSON.parse(init.body);
  assert.equal(sent.repo, "o/r");
  assert.equal(sent.message, "it broke");
  assert.deepEqual(sent.user, { category: "bug", name: "Jo" });
  assert.equal(form.status.textContent, "Thanks.");
  assert.equal(form.stored.__observe_name__, "Jo");
});

test("an empty message sends nothing", async function () {
  let calls = 0;
  const form = load({}, function () { calls += 1; return Promise.resolve({ ok: true }); });
  form.message.value = "   ";
  click(form.send);
  await settle();
  assert.equal(calls, 0);
});

test("a refused or failed send shows an error", async function () {
  const answers = [
    () => Promise.resolve({ ok: false, status: 500 }),
    () => Promise.reject(new Error("down")),
  ];
  for (const answer of answers) {
    const form = load({}, answer);
    form.message.value = "hi";
    click(form.send);
    await settle();
    assert.equal(form.status.textContent, "Could not send.");
    assert.equal(form.send.disabled, false);
  }
});

test("button false builds no trigger, and open() still shows the panel", function () {
  const form = load({ button: false }, function () { return Promise.resolve({ ok: true }); });
  assert.equal(form.trigger, null);
  assert.equal(form.panel.style.display, undefined);
  const api = form.window.__observe__;
  assert.ok(api);
  api.open();
  assert.equal(form.panel.style.display, "block");
  api.close();
  assert.equal(form.panel.style.display, "");
});

test("the trigger is on the page by default", function () {
  const form = load({}, function () { return Promise.resolve({ ok: true }); });
  assert.ok(form.trigger);
});
