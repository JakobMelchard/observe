// Node tests for the feedback form. The shim runs against a fake document that records what it
// builds; `fetch` stands in for the network.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../../src/observe/shim/observe.js", import.meta.url), "utf8");

function element(tag) {
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

function find(root, match) {
  if (match(root)) return root;
  for (const child of root.children) {
    const found = find(child, match);
    if (found) return found;
  }
  return null;
}

function load(config, fetch) {
  const stored = {};
  const body = element("body");
  const window = {
    __OBSERVE_CONFIG__: config,
    fetch: fetch,
    navigator: {},
    console: console,
    localStorage: { getItem: (k) => stored[k] ?? null, setItem: (k, v) => { stored[k] = v; } },
    setTimeout() {},
    addEventListener() {},
    document: { body: body, head: element("head"), createElement: element, addEventListener() {} },
  };
  window.window = window;
  vm.runInNewContext(SOURCE, window);
  const byTag = (tag) => find(body, (e) => e.tag === tag);
  return {
    window: window,
    stored: stored,
    body: body,
    category: byTag("select"),
    message: byTag("textarea"),
    name: byTag("input"),
    send: find(body, (e) => e.className === "observe-send"),
    status: find(body, (e) => e.className === "observe-row").children[0],
    trigger: find(body, (e) => e.className === "observe-btn"),
    panel: find(body, (e) => e.className === "observe-panel"),
  };
}

function settle() {
  return new Promise(function (resolve) { setTimeout(resolve, 20); });
}

test("submit sends the feedback to the endpoint with the token", async function () {
  const calls = [];
  const form = load(
    { feedbackEndpoint: "https://recv.example/feedback", token: "secret", repo: "o/r" },
    function (url, init) { calls.push([url, init]); return Promise.resolve({ ok: true }); },
  );
  form.message.value = "  it broke  ";
  form.category.value = "bug";
  form.name.value = " Jo ";
  form.send.onclick();
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
  form.send.onclick();
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
    form.send.onclick();
    await settle();
    assert.equal(form.status.textContent, "Could not send.");
    assert.equal(form.send.disabled, false);
  }
});

test("button false builds no trigger, and open() still shows the panel", function () {
  const form = load({ button: false }, function () { return Promise.resolve({ ok: true }); });
  assert.equal(form.trigger, null);
  assert.equal(form.panel.style.display, undefined);
  form.window.__observe__.open();
  assert.equal(form.panel.style.display, "block");
  form.window.__observe__.close();
  assert.equal(form.panel.style.display, "");
});

test("the trigger is on the page by default", function () {
  const form = load({}, function () { return Promise.resolve({ ok: true }); });
  assert.ok(form.trigger);
});
