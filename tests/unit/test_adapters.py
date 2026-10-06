"""Adapter tests for the ASGI and http.server middlewares.

The WSGI adapter is covered by ``test_middleware.py``; these two had no
coverage at all, which is how ``http_server`` drifted twice.
"""

import asyncio
import contextlib
import http.client
import json
import threading
import urllib.error
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


def test_asgi_streaming_response_is_not_buffered():
    sent = []
    seen_mid_stream = []

    async def sse(scope, receive, send):
        headers = [(b"content-type", b"text/event-stream")]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"data: 0\n\n", "more_body": True})
        seen_mid_stream.extend(sent)
        await send({"type": "http.response.body", "body": b"data: 1\n\n"})

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "path": "/events", "method": "GET", "headers": []}
    asyncio.run(ObserveASGIMiddleware(sse, ObserveConfig())(scope, None, send))
    assert [m["type"] for m in seen_mid_stream] == ["http.response.start", "http.response.body"]
    assert seen_mid_stream[1]["body"] == b"data: 0\n\n"
    assert len(sent) == 3


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


def test_http_server_patches_get_only_handler():
    class GetOnly(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(HTML)))
            self.end_headers()
            self.wfile.write(HTML)

    patch_handler(GetOnly, ObserveConfig())
    server = ThreadingHTTPServer(("127.0.0.1", 0), GetOnly)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    sink = Recorder()
    router.register(sink)
    try:
        status, _, _ = fetch(f"{url}/__observe__/feedback", json.dumps({"message": "g"}).encode())
        assert status == 200
        assert sink.feedback[0].message == "g"
        with pytest.raises(urllib.error.HTTPError) as err:
            fetch(f"{url}/save", b"{}")
        assert err.value.code == 501
    finally:
        server.shutdown()
        server.server_close()


def test_http_server_otlp_ignores_query_string(http_url):
    sink = Recorder()
    router.register(sink)
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": [{"name": "qs"}]}]}]}
    fetch(f"{http_url}/__observe__/otlp/v1/traces?x=1", json.dumps(payload).encode())
    assert sink.errors[0].message == "qs"


# --------------------------------------------------------------------------
# Ingest limits
# --------------------------------------------------------------------------

FEEDBACK = "/__observe__/feedback"
LIMITS = {"max_body_bytes": 64, "feedback_per_minute": 2}


def asgi_post(app, chunks, headers=()):
    """POST ``chunks`` to the feedback route; returns the status and the receive count."""
    scope = {
        "type": "http",
        "path": FEEDBACK,
        "method": "POST",
        "headers": [(b"content-type", b"application/json"), *headers],
        "client": ("10.0.0.1", 50000),
    }
    pending = list(chunks)
    reads = 0
    sent = []

    async def receive():
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": pending.pop(0), "more_body": bool(pending)}

    async def send(msg):
        sent.append(msg)

    asyncio.run(app(scope, receive, send))
    return sent[0]["status"], reads


def test_asgi_refuses_a_declared_oversize_unread():
    sink = Recorder()
    router.register(sink)
    app = ObserveASGIMiddleware(demo_app, ObserveConfig(**LIMITS))
    status, reads = asgi_post(app, [b"x" * 65], [(b"content-length", b"65")])
    assert (status, reads) == (413, 0)
    assert sink.feedback == []


def test_asgi_stops_reading_a_body_that_outgrows_the_cap():
    sink = Recorder()
    router.register(sink)
    app = ObserveASGIMiddleware(demo_app, ObserveConfig(**LIMITS))
    status, reads = asgi_post(app, [b"x" * 40] * 50)
    assert (status, reads) == (413, 2)
    assert sink.feedback == []


def test_asgi_refuses_cross_site_posts():
    sink = Recorder()
    router.register(sink)
    app = ObserveASGIMiddleware(demo_app, ObserveConfig(**LIMITS))
    assert asgi_post(app, [b"{}"], [(b"sec-fetch-site", b"cross-site")])[0] == 403
    mismatch = [(b"origin", b"https://other.test"), (b"host", b"app.test")]
    assert asgi_post(app, [b"{}"], mismatch)[0] == 403
    assert sink.feedback == []
    match = [(b"origin", b"http://app.test"), (b"host", b"app.test")]
    assert asgi_post(app, [b"{}"], match)[0] == 200


def test_asgi_refuses_posts_that_come_too_fast():
    app = ObserveASGIMiddleware(demo_app, ObserveConfig(**LIMITS))
    assert [asgi_post(app, [b"{}"])[0] for _ in range(3)] == [200, 200, 429]


@pytest.fixture
def limited_url():
    class Limited(DemoHandler):
        protocol_version = "HTTP/1.1"

    patch_handler(Limited, ObserveConfig(**LIMITS))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Limited)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def post_status(url, data=b"{}", headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code


def test_http_server_refuses_oversized_posts(limited_url):
    sink = Recorder()
    router.register(sink)
    assert post_status(limited_url + FEEDBACK, b"x" * 65) == 413
    assert sink.feedback == []


def test_http_server_closes_the_connection_on_an_unread_body(limited_url):
    """Left open, the unread body would be parsed as the next request."""
    host = limited_url.removeprefix("http://")
    conn = http.client.HTTPConnection(host, timeout=5)
    conn.request("POST", FEEDBACK, body=b"x" * 65)
    resp = conn.getresponse()
    assert resp.status == 413
    resp.read()
    with contextlib.suppress(ConnectionResetError):
        assert conn.sock.recv(1) == b""
    conn.close()


def test_http_server_refuses_cross_site_posts(limited_url):
    sink = Recorder()
    router.register(sink)
    assert post_status(limited_url + FEEDBACK, headers={"Sec-Fetch-Site": "cross-site"}) == 403
    assert post_status(limited_url + FEEDBACK, headers={"Origin": "https://other.test"}) == 403
    assert sink.feedback == []
    assert post_status(limited_url + FEEDBACK, headers={"Origin": limited_url}) == 200


def test_http_server_refuses_posts_that_come_too_fast(limited_url):
    assert [post_status(limited_url + FEEDBACK) for _ in range(3)] == [200, 200, 429]
