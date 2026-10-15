// Node tests for the service worker. It runs in a vm context against a fake
// IndexedDB that holds the queue in a Map, and a fake `fetch`. The queue is driven through the
// worker's own events, the way an app worker that importScripts() it sees it.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const SOURCE = readFileSync(
  new URL("../../src/observe/shim/observe.sw.js", import.meta.url),
  "utf8",
);
const OTLP = "http://app.test/__observe__/otlp/v1/traces";

/**
 * @typedef {{ id: number, body: string }} Row
 * @typedef {{ result: unknown, onsuccess?: (e: { target: FakeRequest }) => void }} FakeRequest
 * @typedef {{ objectStore(): object, oncomplete?: () => void }} FakeTransaction
 * @typedef {{ body: string }} FetchInit A resend always passes one.
 * @typedef {(input: Request | string, init: FetchInit) => Promise<unknown>} FakeFetch
 * @typedef {(e: object) => void} Listener
 */

/**
 * @param {Map<number, Row>} rows the committed queue
 * @returns {{ open(): FakeRequest }} an IndexedDB with one store kept in rows
 */
function fakeIndexedDB(rows) {
  let nextId = 1;
  /**
   * Like IndexedDB, the result arrives after the caller attached onsuccess.
   *
   * @param {unknown} [result] what the request yields
   * @returns {FakeRequest} the pending request
   */
  function request(result) {
    /** @type {FakeRequest} */
    const req = { result: result };
    queueMicrotask(function () {
      if (req.onsuccess) req.onsuccess({ target: req });
    });
    return req;
  }
  /** @returns {FakeTransaction} a transaction that commits on the next tick */
  function transaction() {
    /** @type {Row[]} */
    const added = [];
    /** @type {number[]} */
    const deleted = [];
    /** @type {FakeTransaction} */
    const tx = {
      objectStore() {
        return {
          /** @param {{ body: string }} value the entry */
          add(value) {
            added.push(Object.assign({ id: nextId }, value));
            return request(nextId++);
          },
          count() {
            return request(rows.size);
          },
          getAll() {
            return request(Array.from(rows.values()));
          },
          clear() {
            rows.clear();
            return request();
          },
          /** @param {number} id the key */
          delete(id) {
            deleted.push(id);
            return request();
          },
        };
      },
    };
    // A write only shows once its transaction has committed.
    setTimeout(function () {
      added.forEach(function (row) {
        rows.set(row.id, row);
      });
      deleted.forEach(function (id) {
        rows.delete(id);
      });
      if (tx.oncomplete) tx.oncomplete();
    }, 0);
    return tx;
  }
  const db = {
    objectStoreNames: {
      contains() {
        return true;
      },
    },
    transaction: transaction,
  };
  return {
    open() {
      return request(db);
    },
  };
}

/**
 * Runs the worker, or a host worker script that imports it, in a fresh context.
 *
 * @param {FakeFetch} fetch stands in for the network
 * @param {string} [host] a host worker script to run instead of the worker itself
 */
function load(fetch, host) {
  /** @type {Map<number, Row>} */
  const rows = new Map();
  /** @type {Record<string, Listener>} */
  const listeners = {};
  /** @type {string[]} */
  const tags = [];
  /** @type {Record<string, unknown> & { fetch: FakeFetch }} */
  const sw = {
    indexedDB: fakeIndexedDB(rows),
    fetch: fetch,
    console: console,
    URL: URL,
    Response: Response,
    clients: { claim() {} },
    registration: {
      sync: {
        register(/** @type {string} */ tag) {
          tags.push(tag);
          return Promise.resolve();
        },
      },
    },
    addEventListener(/** @type {string} */ type, /** @type {Listener} */ fn) {
      listeners[type] = fn;
    },
  };
  sw.self = sw;
  sw.importScripts = function (/** @type {string} */ url) {
    assert.equal(url, "/__observe__/observe.sw.js");
    vm.runInContext(SOURCE, sw);
  };
  vm.createContext(sw);
  vm.runInContext(host || SOURCE, sw);
  return { sw: sw, rows: rows, listeners: listeners, tags: tags };
}

function offline() {
  return Promise.reject(new TypeError("Failed to fetch"));
}

/** @typedef {ReturnType<typeof load>} Worker */

/**
 * A POST that fails offline lands in the queue once the fetch event has finished.
 *
 * @param {Worker} worker the loaded worker
 * @param {string} body the OTLP body
 */
async function enqueue(worker, body) {
  /** @type {Promise<unknown>[]} */
  const waits = [];
  const live = worker.sw.fetch;
  worker.sw.fetch = offline;
  worker.listeners.fetch({
    request: new Request(OTLP, { method: "POST", body: body }),
    respondWith(/** @type {Promise<unknown>} */ promise) {
      waits.push(promise);
    },
    waitUntil(/** @type {Promise<unknown>} */ promise) {
      waits.push(promise);
    },
  });
  worker.sw.fetch = live;
  await waits[0];
  await Promise.all(waits);
}

/**
 * @param {Worker} worker the loaded worker
 * @returns {Promise<unknown>} what the sync event waits on
 */
function flush(worker) {
  /** @type {Promise<unknown>[]} */
  const waits = [];
  worker.listeners.sync({
    tag: "observe-flush",
    waitUntil(/** @type {Promise<unknown>} */ promise) {
      waits.push(promise);
    },
  });
  assert.equal(waits.length, 1);
  return waits[0];
}

/**
 * @param {Worker} worker the loaded worker
 * @returns {string[]} the queued bodies in order
 */
function bodies(worker) {
  return Array.from(worker.rows.values()).map(function (row) {
    return row.body;
  });
}

test("queue entries survive a failed flush", async function () {
  const worker = load(offline);
  await enqueue(worker, "{}");
  assert.equal(worker.rows.size, 1);

  await assert.rejects(flush(worker));
  assert.equal(worker.rows.size, 1);
});

test("only delivered entries leave the queue", async function () {
  /** @type {string[]} */
  const sent = [];
  const worker = load(function (_url, init) {
    sent.push(init.body);
    return init.body === "lost" ? offline() : Promise.resolve({ ok: true, status: 200 });
  });
  await enqueue(worker, "lost");
  await enqueue(worker, "delivered");

  await assert.rejects(flush(worker));
  assert.deepEqual(sent, ["lost", "delivered"]);
  assert.deepEqual(bodies(worker), ["lost"]);
});

test("an answer that a later try could change keeps the entry", async function () {
  const worker = load(function (_url, init) {
    return Promise.resolve({ ok: false, status: Number(init.body) });
  });
  for (const status of ["400", "413", "429", "500", "503"]) {
    await enqueue(worker, status);
  }

  await assert.rejects(flush(worker));
  assert.deepEqual(bodies(worker), ["429", "500", "503"]);
});

test("the sync event waits for the flush", async function () {
  let delivered = false;
  const worker = load(function () {
    return new Promise(function (resolve) {
      setTimeout(function () {
        delivered = true;
        resolve({ ok: true, status: 200 });
      }, 10);
    });
  });
  await enqueue(worker, "{}");

  await flush(worker);
  assert.equal(delivered, true);
  assert.equal(worker.rows.size, 0);
});

test("a request that fails offline is queued and asks for a sync", async function () {
  // Like the real fetch, reading the request uses its body up.
  const worker = load(function (request) {
    return /** @type {Request} */ (request).text().then(offline);
  });
  /** @type {Promise<unknown>[]} */
  const waits = [];
  /** @type {Promise<Response>[]} */
  const responses = [];
  worker.listeners.fetch({
    request: new Request(OTLP, { method: "POST", body: '{"resourceSpans":[]}' }),
    respondWith(/** @type {Promise<Response>} */ promise) {
      responses.push(promise);
    },
    waitUntil(/** @type {Promise<unknown>} */ promise) {
      waits.push(promise);
    },
  });

  assert.equal(responses.length, 1);
  assert.equal((await responses[0]).status, 200);
  // The event stays alive until the write has committed, not just until it was issued.
  assert.equal(worker.rows.size, 0);
  await Promise.all(waits);
  assert.deepEqual(bodies(worker), ['{"resourceSpans":[]}']);
  assert.deepEqual(worker.tags, ["observe-flush"]);
});

test("overlapping flushes share one run and post each entry once", async function () {
  /** @type {string[]} */
  const sent = [];
  const worker = load(function (_url, init) {
    sent.push(init.body);
    return new Promise(function (resolve) {
      setTimeout(function () {
        resolve({ ok: true, status: 200 });
      }, 10);
    });
  });
  await enqueue(worker, "a");
  await enqueue(worker, "b");

  const first = flush(worker);
  const second = flush(worker);
  assert.equal(first, second);
  await Promise.all([first, second]);
  assert.deepEqual(sent.sort(), ["a", "b"]);
  assert.equal(worker.rows.size, 0);

  // A later flush is a new run.
  await enqueue(worker, "c");
  await flush(worker);
  assert.deepEqual(sent.sort(), ["a", "b", "c"]);
});

test("importScripts keeps the host worker's globals and serves the OTLP route", async function () {
  const worker = load(
    offline,
    [
      'function openDB() { return "host"; }',
      'var flushing = "host";',
      'importScripts("/__observe__/observe.sw.js");',
    ].join("\n"),
  );
  const openDB = /** @type {() => string} */ (worker.sw.openDB);
  assert.equal(openDB(), "host");
  assert.equal(worker.sw.flushing, "host");

  await enqueue(worker, '{"resourceSpans":[]}');
  assert.deepEqual(bodies(worker), ['{"resourceSpans":[]}']);
});

test("requests outside the observe route are left to the host worker", function () {
  const worker = load(offline);
  let answered = false;
  worker.listeners.fetch({
    request: new Request("http://app.test/api", { method: "POST", body: "{}" }),
    respondWith() {
      answered = true;
    },
    waitUntil() {},
  });
  assert.equal(answered, false);
});
