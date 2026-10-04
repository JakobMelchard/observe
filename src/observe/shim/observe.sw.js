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

function queueRequest(url, body, timestamp) {
  return openDB().then(function (db) {
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
  }).catch(function (err) {
    console.error("observe sw: failed to queue request", err);
  });
}

// Resends the queue. An entry leaves the store only once its resend went through; the returned
// promise rejects when any did not, which is what makes a sync event retry later.
function flushQueue() {
  return openDB().then(function (db) {
    return new Promise(function (resolve, reject) {
      var req = db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).getAll();
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    }).then(function (items) {
      return Promise.all(items.map(function (item) {
        var headers = { "Content-Type": "application/json", "X-Observe-Timestamp": item.timestamp || new Date().toISOString() };
        return fetch(item.url, { method: "POST", headers: headers, body: item.body }).then(function () {
          db.transaction(STORE_NAME, "readwrite").objectStore(STORE_NAME).delete(item.id);
        });
      }));
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
