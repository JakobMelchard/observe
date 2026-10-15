// The page may importScripts() this into the app's own worker, so nothing is left on the global scope.
(/** @param {ServiceWorkerGlobalScope} sw */ function (sw) {
  var MAX_QUEUE = 500;
  var DB_NAME = "observe-buffer";
  var STORE_NAME = "requests";

  /** @returns {Promise<IDBDatabase>} the queue database, created on first use */
  function openDB() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: "id", autoIncrement: true });
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  // Settles after the write has committed, so a fetch event that waits on it stays alive that long.
  /**
   * @param {string} url where the request was going
   * @param {string} body its OTLP JSON
   * @param {string} timestamp ISO time it failed
   * @returns {Promise<void>} settles once queued, or once the failure is logged
   */
  function queueRequest(url, body, timestamp) {
    return openDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_NAME, "readwrite");
        var store = tx.objectStore(STORE_NAME);
        store.add({ url: url, body: body, timestamp: timestamp });
        var countReq = store.count();
        countReq.onsuccess = function () {
          if (countReq.result <= MAX_QUEUE) return;
          var cursorReq = store.openCursor();
          cursorReq.onsuccess = function () {
            var cursor = cursorReq.result;
            if (cursor) { cursor.delete(); }
          };
        };
        tx.oncomplete = function () { resolve(undefined); };
        tx.onerror = tx.onabort = function () { reject(tx.error); };
      });
    }).catch(function (err) {
      console.error("observe sw: failed to queue request", err);
    });
  }

  // Resends one queued entry and deletes it once the server gave a final answer. A network failure,
  // a 5xx or a 429 may go differently on a later try, so the entry stays; any other answer would be
  // the same next time, so the entry goes. Settles after the delete has committed.
  /**
   * @param {IDBDatabase} db the queue database
   * @param {QueuedRequest} item the entry to resend
   * @returns {Promise<void>} settles after the delete, rejects while the entry stays
   */
  function resend(db, item) {
    var headers = { "Content-Type": "application/json" };
    return fetch(item.url, { method: "POST", headers: headers, body: item.body }).then(function (resp) {
      if (resp.status >= 500 || resp.status === 429) throw new Error("observe sw: resend answered " + resp.status);
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_NAME, "readwrite");
        tx.objectStore(STORE_NAME).delete(item.id);
        tx.oncomplete = function () { resolve(undefined); };
        tx.onerror = tx.onabort = function () { reject(tx.error); };
      });
    });
  }

  // Resends the queue. The returned promise settles after every resend has, and rejects when any
  // entry is still queued, which is what makes a sync event retry later. A sync and an online
  // event can overlap; they share one run, so no entry is read and posted twice.
  /** @type {Promise<void> | null} */
  var flushing = null;
  /** @returns {Promise<void>} the running flush, or a new one */
  function flushQueue() {
    if (!flushing) {
      flushing = startFlush().then(
        function (v) { flushing = null; return v; },
        function (e) { flushing = null; throw e; }
      );
    }
    return flushing;
  }

  /** @returns {Promise<void>} rejects when any entry is still queued */
  function startFlush() {
    return openDB().then(function (db) {
      return /** @type {Promise<QueuedRequest[]>} */ (new Promise(function (resolve, reject) {
        var req = db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).getAll();
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      })).then(function (items) {
        var kept = 0;
        return Promise.all(items.map(function (item) {
          return resend(db, item).catch(function () { kept += 1; });
        })).then(function () {
          if (kept) throw new Error("observe sw: " + kept + " queued requests not resent");
        });
      });
    });
  }

  sw.addEventListener("fetch", function (event) {
    var url = new URL(event.request.url);
    if (url.pathname.indexOf("/__observe__/otlp") !== 0) return;

    // fetch uses the body up, so the copy to queue is taken before it runs.
    var copy = event.request.clone();
    event.respondWith(
      fetch(event.request).catch(function () {
        event.waitUntil(
          copy.text().then(function (body) {
            return queueRequest(url.href, body, new Date().toISOString());
          }).then(function () {
            // Background Sync is not available in every browser.
            var reg = /** @type {SyncRegistration} */ (sw.registration);
            if (reg.sync) return reg.sync.register("observe-flush");
          }).catch(function (err) {
            console.error("observe sw: failed to register sync", err);
          })
        );
        return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
      })
    );
  });

  sw.addEventListener("sync", /** @param {Event} e */ function (e) {
    var event = /** @type {SyncEvent} */ (e);
    if (event.tag === "observe-flush") {
      event.waitUntil(flushQueue());
    }
  });

  sw.addEventListener("online", function () {
    // Nothing retries here; what failed stays queued for the next flush.
    flushQueue().catch(function () {});
  });

  sw.addEventListener("activate", function (event) {
    event.waitUntil(sw.clients.claim());
  });
})(/** @type {ServiceWorkerGlobalScope} */ (/** @type {unknown} */ (self)));

// Types sit after the IIFE: a JSDoc block in front of it would be read twice.

/**
 * One request kept for a later resend.
 *
 * @typedef {object} QueuedRequest
 * @property {number} id store key
 * @property {string} url where it was going
 * @property {string} body the OTLP JSON
 * @property {string} timestamp ISO time it was queued
 */

/**
 * Background Sync is not in the TypeScript DOM libs.
 *
 * @typedef {ExtendableEvent & { tag: string }} SyncEvent
 * @typedef {ServiceWorkerRegistration & { sync?: { register(tag: string): Promise<void> } }} SyncRegistration
 */
