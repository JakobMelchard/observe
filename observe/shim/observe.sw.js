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
  openDB().then(function (db) {
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

function flushQueue() {
  openDB().then(function (db) {
    var tx = db.transaction(STORE_NAME, "readwrite");
    var store = tx.objectStore(STORE_NAME);
    var req = store.getAll();
    req.onsuccess = function () {
      var items = req.result;
      store.clear();
      items.forEach(function (item) {
        var headers = { "Content-Type": "application/json", "X-Observe-Timestamp": item.timestamp || new Date().toISOString() };
        fetch(item.url, { method: "POST", headers: headers, body: item.body }).catch(function () {});
      });
    };
  }).catch(function () {});
}

self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);
  if (url.pathname.indexOf("/__observe__/otlp") !== 0) return;

  event.respondWith(
    fetch(event.request).catch(function () {
      event.waitUntil(
        event.request.clone().text().then(function (body) {
          queueRequest(url.href, body, new Date().toISOString());
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
  flushQueue();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(clients.claim());
});
