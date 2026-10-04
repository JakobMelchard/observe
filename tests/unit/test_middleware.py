"""Unit tests for ObserveMiddleware using werkzeug test client."""

import json

import pytest
from werkzeug.test import Client

from observe import router
from observe.config.config import ObserveConfig
from observe.middleware.wsgi import ObserveMiddleware
from tests.fixture import app as fixture_app


@pytest.fixture(autouse=True)
def reset_router():
    router._sinks.clear()
    router.background = False
    yield


@pytest.fixture
def client():
    cfg = ObserveConfig()
    wrapped = ObserveMiddleware(fixture_app.app, cfg)
    return Client(wrapped)


def test_get_html_contains_observe_script(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"observe.js" in resp.data


def test_content_length_matches_injected_body(client):
    resp = client.get("/")
    assert b"observe.js" in resp.data
    assert int(resp.headers["Content-Length"]) == len(resp.data)


def test_head_keeps_declared_content_length():
    def head(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/html"), ("Content-Length", "120")])
        return []

    resp = Client(ObserveMiddleware(head, ObserveConfig())).head("/")
    assert resp.headers["Content-Length"] == "120"


class Events:
    """An event stream that records how far it was read and whether it was closed."""

    def __init__(self):
        self.produced = 0
        self.closed = False

    def __iter__(self):
        for n in range(3):
            self.produced += 1
            yield b"data: %d\n\n" % n

    def close(self):
        self.closed = True


def call(app, path="/"):
    started = []
    environ = {"PATH_INFO": path, "REQUEST_METHOD": "GET"}
    chunks = ObserveMiddleware(app, ObserveConfig())(environ, lambda *a: started.append(a))
    return started, iter(chunks)


def test_streaming_response_is_not_buffered():
    events = Events()

    def sse(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/event-stream")])
        return events

    started, chunks = call(sse)
    assert next(chunks) == b"data: 0\n\n"
    assert events.produced == 1
    assert started[0][0] == "200 OK"


def test_generator_app_is_passed_through():
    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        yield b"a"
        yield b"b"

    started, chunks = call(app)
    assert list(chunks) == [b"a", b"b"]
    assert len(started) == 1


@pytest.mark.parametrize("content_type", ["text/event-stream", "text/html"])
def test_app_iterable_is_closed(content_type):
    events = Events()

    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", content_type)])
        return events

    _, chunks = call(app)
    assert b"".join(chunks) == b"data: 0\n\ndata: 1\n\ndata: 2\n\n"
    assert events.closed


def test_get_html_contains_config_json(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"__OBSERVE_CONFIG__" in resp.data


def test_config_json_shape(client):
    resp = client.get("/__observe__/config")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "endpoint" in data
    assert "feedbackLabel" in data
    assert "enrichHook" in data
    assert "registerSw" in data


def test_binary_response_not_injected(client):
    resp = client.get("/binary")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    assert b"observe.js" not in resp.data


def test_serve_observe_js(client):
    resp = client.get("/__observe__/observe.js")
    assert resp.status_code == 200
    assert resp.content_type == "application/javascript"
    assert len(resp.data) > 0


def test_serve_observe_sw_js(client):
    resp = client.get("/__observe__/observe.sw.js")
    assert resp.status_code == 200
    assert resp.content_type == "application/javascript"
    assert len(resp.data) > 0


def test_feedback_calls_router(client):
    events = []

    class TestSink:
        def push_error(self, event):
            pass

        def push_feedback(self, event):
            events.append(event)

    router.register(TestSink())
    resp = client.post(
        "/__observe__/feedback",
        data=json.dumps(
            {
                "message": "test feedback",
                "timestamp": "2025-01-01T00:00:00Z",
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert len(events) == 1
    assert events[0].message == "test feedback"


def test_otlp_calls_router(client):
    events = []

    class TestSink:
        def push_error(self, event):
            events.append(event)

        def push_feedback(self, event):
            pass

    router.register(TestSink())
    otlp_payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "name": "test-span",
                                "traceId": "abc123",
                                "spanId": "def456",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000000000000",
                                "attributes": [{"key": "level", "value": {"stringValue": "error"}}],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    resp = client.post(
        "/__observe__/otlp/v1/traces",
        data=json.dumps(otlp_payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert len(events) == 1
    assert events[0].message == "test-span"
    assert events[0].trace_id == "abc123"


def test_app_passthrough_unchanged(client):
    resp = client.post("/save", data=json.dumps({"ok": True}), content_type="application/json")
    assert resp.status_code == 200
    assert json.loads(resp.data) == {}


def test_app_error_not_swallowed(client):
    resp = client.post("/fail")
    assert resp.status_code == 500


def test_no_sink_registered_feedback_returns_200(client):
    resp = client.post(
        "/__observe__/feedback",
        data=json.dumps({"message": "test"}),
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_multiple_sinks_called(client):
    events = []

    class Sink1:
        def push_error(self, e):
            pass

        def push_feedback(self, e):
            events.append(1)

    class Sink2:
        def push_error(self, e):
            pass

        def push_feedback(self, e):
            events.append(2)

    router.register(Sink1())
    router.register(Sink2())
    client.post(
        "/__observe__/feedback",
        data=json.dumps({"message": "test"}),
        content_type="application/json",
    )
    assert events == [1, 2]


def test_otlp_logs_calls_router(client):
    events = []

    class TestSink:
        def push_error(self, event):
            events.append(event)

        def push_feedback(self, event):
            pass

    router.register(TestSink())
    otlp_payload = {
        "resourceLogs": [
            {
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "body": {"stringValue": "test-log"},
                                "timeUnixNano": "1700000000000000000",
                                "attributes": [
                                    {"key": "severity", "value": {"stringValue": "warning"}}
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    resp = client.post(
        "/__observe__/otlp/v1/logs", data=json.dumps(otlp_payload), content_type="application/json"
    )
    assert resp.status_code == 200
    assert len(events) == 1
    assert events[0].message == "test-log"
    assert events[0].level == "warning"
