"""Adapter tests for the ASGI and http.server middlewares.

The WSGI adapter is covered by ``test_middleware.py``; these two had no
coverage at all, which is how ``http_server`` drifted twice.
"""

import asyncio
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from observe import router
from observe.config.config import ObserveConfig
from observe.middleware.asgi import ObserveASGIMiddleware
from observe.middleware.http_server import patch_handler

HTML = b"<!DOCTYPE html><html><head><title>t</title></head><body>hi</body></html>"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


@pytest.fixture(autouse=True)
def reset_router():
    router._sinks.clear()
    router.background = False
    yield


class Recorder:
    def __init__(self):
        self.errors = []
        self.feedback = []

    def push_error(self, event):
        self.errors.append(event)

    def push_feedback(self, event):
        self.feedback.append(event)


# --------------------------------------------------------------------------
# ASGI
# --------------------------------------------------------------------------


async def demo_app(scope, receive, send):
    body, content_type = {
        "/": (HTML, b"text/html"),
        "/logo.png": (PNG, b"image/png"),
    }.get(scope["path"], (b"{}", b"application/json"))
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", content_type),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def asgi_request(path, method="GET", body=b"", content_type=""):
    app = ObserveASGIMiddleware(demo_app, ObserveConfig())
    headers = [(b"content-type", content_type.encode())] if content_type else []
    scope = {"type": "http", "path": path, "method": method, "headers": headers}
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        sent.append(msg)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start, payload


def test_asgi_injects_html():
    start, body = asgi_request("/")
    assert start["status"] == 200
    assert b"observe.js" in body
    assert b"__OBSERVE_CONFIG__" in body


def test_asgi_rewrites_content_length():
    start, body = asgi_request("/")
    length = next(int(v) for k, v in start["headers"] if k.lower() == b"content-length")
    assert length == len(body)


def test_asgi_skips_binary():
    _, body = asgi_request("/logo.png")
    assert body == PNG


def test_asgi_serves_shim():
    start, body = asgi_request("/__observe__/observe.js")
    assert start["status"] == 200
    assert (b"content-type", b"application/javascript") in start["headers"]
    assert len(body) > 0


def test_asgi_feedback_reaches_router():
    sink = Recorder()
    router.register(sink)
    start, _ = asgi_request(
        "/__observe__/feedback",
        "POST",
        json.dumps({"message": "asgi"}).encode(),
        "application/json",
    )
    assert start["status"] == 200
    assert sink.feedback[0].message == "asgi"


def test_asgi_otlp_reaches_router():
    sink = Recorder()
    router.register(sink)
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": [{"name": "span"}]}]}]}
    asgi_request(
        "/__observe__/otlp/v1/traces", "POST", json.dumps(payload).encode(), "application/json"
    )
    assert sink.errors[0].message == "span"


def test_asgi_passes_through_non_http():
    app = ObserveASGIMiddleware(demo_app, ObserveConfig())
    seen = []

    async def lifespan(scope, receive, send):
        seen.append(scope["type"])

    app.app = lifespan
    asyncio.run(app({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


# --------------------------------------------------------------------------
# http.server
# --------------------------------------------------------------------------


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/logo.png":
            self._reply(PNG, "image/png")
        else:
            self._reply(HTML, "text/html")

    def do_POST(self):
        self._reply(b"{}", "application/json")


@pytest.fixture(scope="module")
def http_url():
    patch_handler(DemoHandler, ObserveConfig())
    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def fetch(url, data=None, content_type="application/json"):
    req = urllib.request.Request(url, data=data)
    if data is not None:
        req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, dict(resp.headers), resp.read()


def test_http_server_injects_html(http_url):
    status, headers, body = fetch(f"{http_url}/")
    assert status == 200
    assert b"observe.js" in body
    assert int(headers["Content-Length"]) == len(body)


def test_http_server_skips_binary(http_url):
    _, _, body = fetch(f"{http_url}/logo.png")
    assert body == PNG


def test_http_server_serves_shim(http_url):
    status, headers, body = fetch(f"{http_url}/__observe__/observe.js")
    assert status == 200
    assert headers["Content-Type"] == "application/javascript"
    assert len(body) > 0


def test_http_server_feedback_reaches_router(http_url):
    sink = Recorder()
    router.register(sink)
    status, _, _ = fetch(
        f"{http_url}/__observe__/feedback", json.dumps({"message": "raw"}).encode()
    )
    assert status == 200
    assert sink.feedback[0].message == "raw"


def test_http_server_otlp_ignores_query_string(http_url):
    sink = Recorder()
    router.register(sink)
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": [{"name": "qs"}]}]}]}
    fetch(f"{http_url}/__observe__/otlp/v1/traces?x=1", json.dumps(payload).encode())
    assert sink.errors[0].message == "qs"
