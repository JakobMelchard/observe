var CACHE_NAME = "observe-queue-v1";
var MAX_QUEUE = 500;
var DB_NAME = "observe-buffer";
var STORE_NAME = "requests";

function openDB() {
  return new Promise(function (resolve, reject) {
    var req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = function (e) {
      var db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = function () { resolve(req.result); };
    req.onerror = function () { reject(req.error); };
  });
}

// Settles after the write has committed, so a fetch event that waits on it stays alive that long.
function queueRequest(url, body, timestamp) {
  return openDB().then(function (db) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, "readwrite");
      var store = tx.objectStore(STORE_NAME);
      store.add({ url: url, body: body, timestamp: timestamp });
      var countReq = store.count();
      countReq.onsuccess = function () {
        if (countReq.result > MAX_QUEUE) {
          var cursorReq = store.openCursor();
          cursorReq.onsuccess = function (e) {
            var cursor = e.target.result;
            if (cursor) { cursor.delete(); }
          };
        }
      };
      tx.oncomplete = resolve;
      tx.onerror = tx.onabort = function () { reject(tx.error); };
    });
  }).catch(function (err) {
    console.error("observe sw: failed to queue request", err);
  });
}

// Resends one queued entry and deletes it once the server gave a final answer. A network failure,
// a 5xx or a 429 may go differently on a later try, so the entry stays; any other answer would be
// the same next time, so the entry goes. Settles after the delete has committed.
function resend(db, item) {
  var headers = { "Content-Type": "application/json", "X-Observe-Timestamp": item.timestamp || new Date().toISOString() };
  return fetch(item.url, { method: "POST", headers: headers, body: item.body }).then(function (resp) {
    if (resp.status >= 500 || resp.status === 429) throw new Error("observe sw: resend answered " + resp.status);
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).delete(item.id);
      tx.oncomplete = resolve;
      tx.onerror = tx.onabort = function () { reject(tx.error); };
    });
  });
}

// Resends the queue. The returned promise settles after every resend has, and rejects when any
// entry is still queued, which is what makes a sync event retry later. A sync and an online
// event can overlap; they share one run, so no entry is read and posted twice.
var flushing = null;
function flushQueue() {
  if (!flushing) {
    flushing = startFlush().then(
      function (v) { flushing = null; return v; },
      function (e) { flushing = null; throw e; }
    );
  }
  return flushing;
}

function startFlush() {
  return openDB().then(function (db) {
    return new Promise(function (resolve, reject) {
      var req = db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).getAll();
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    }).then(function (items) {
      var kept = 0;
      return Promise.all(items.map(function (item) {
        return resend(db, item).catch(function () { kept += 1; });
      })).then(function () {
        if (kept) throw new Error("observe sw: " + kept + " queued requests not resent");
      });
    });
  });
}

self.addEventListener("fetch", function (event) {
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
          if (self.registration.sync) return self.registration.sync.register("observe-flush");
        }).catch(function (err) {
          console.error("observe sw: failed to register sync", err);
        })
      );
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    })
  );
});

self.addEventListener("sync", function (event) {
  if (event.tag === "observe-flush") {
    event.waitUntil(flushQueue());
  }
});

self.addEventListener("online", function () {
  // Nothing retries here; what failed stays queued for the next flush.
  flushQueue().catch(function () {});
});

self.addEventListener("activate", function (event) {
  event.waitUntil(clients.claim());
});
