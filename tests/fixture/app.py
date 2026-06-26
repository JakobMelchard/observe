"""Plain WSGI test fixture. No observe imports."""

import time
from wsgiref.simple_server import make_server

INDEX = b"""<!DOCTYPE html>
<html>
<head><title>Observe Fixture</title></head>
<body>
  <button id="save">Save</button>
  <button id="fail">Trigger Error</button>
  <button id="feedback">Feedback</button>
  <script>
    window.__observe_enrich__ = function () {
      return { fixture: true, page: "index" };
    };
    document.getElementById("save").onclick = function () {
      fetch("/save", { method: "POST", body: JSON.stringify({ ok: true }) });
    };
    document.getElementById("fail").onclick = function () {
      fetch("/fail", { method: "POST" });
    };
  </script>
</body>
</html>"""

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 67


def app(environ, start_response):
    path = environ["PATH_INFO"]
    method = environ["REQUEST_METHOD"]

    if path == "/" or path == "":
        start_response(
            "200 OK", [("Content-Type", "text/html"), ("Content-Length", str(len(INDEX)))]
        )
        return [INDEX]

    if path == "/save" and method == "POST":
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b"{}"]

    if path == "/fail" and method == "POST":
        start_response("500 Internal Server Error", [("Content-Type", "application/json")])
        return [b'{"error":"fail"}']

    if path == "/stream" and method == "GET":
        start_response(
            "200 OK", [("Content-Type", "text/html"), ("Content-Length", str(len(INDEX)))]
        )
        return [INDEX]

    if path == "/binary" and method == "GET":
        start_response("200 OK", [("Content-Type", "image/png"), ("Content-Length", str(len(PNG)))])
        return [PNG]

    if path == "/slow" and method == "GET":
        time.sleep(0.01)
        start_response(
            "200 OK", [("Content-Type", "text/html"), ("Content-Length", str(len(INDEX)))]
        )
        return [INDEX]

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"not found"]


if __name__ == "__main__":
    port = int(__import__("os").environ.get("PORT", "8765"))
    httpd = make_server("127.0.0.1", port, app)
    print(f"Fixture listening on :{port}")
    httpd.serve_forever()
