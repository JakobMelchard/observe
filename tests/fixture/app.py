"""Plain WSGI test fixture. No observe imports."""

INDEX = b"""<!DOCTYPE html>
<html>
<head><title>Observe Fixture</title></head>
<body></body>
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

    if path == "/binary" and method == "GET":
        start_response("200 OK", [("Content-Type", "image/png"), ("Content-Length", str(len(PNG)))])
        return [PNG]

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"not found"]
