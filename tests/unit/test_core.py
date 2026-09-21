"""Unit tests for the transport-agnostic core shared by every middleware."""

import json
import threading

import pytest

from observe import router
from observe.config.config import ObserveConfig
from observe.core import JAVASCRIPT, JSON, ObserveCore


@pytest.fixture(autouse=True)
def reset_router():
    router._sinks.clear()
    router.background = False
    yield


@pytest.fixture
def core():
    return ObserveCore(ObserveConfig())


class Recorder:
    def __init__(self):
        self.errors = []
        self.feedback = []

    def push_error(self, event):
        self.errors.append(event)

    def push_feedback(self, event):
        self.feedback.append(event)


@pytest.mark.parametrize(
    ("path", "method", "kind", "needs_body"),
    [
        ("/__observe__/observe.js", "GET", "shim", False),
        ("/__observe__/observe.sw.js", "GET", "shim", False),
        ("/__observe__/config", "GET", "config", False),
        ("/__observe__/feedback", "POST", "feedback", True),
        ("/__observe__/otlp/v1/traces", "POST", "otlp", True),
        ("/__observe__/otlp/v1/logs", "POST", "otlp", True),
    ],
)
def test_route_matches(core, path, method, kind, needs_body):
    route = core.route(path, method)
    assert route is not None
    assert route.kind == kind
    assert route.needs_body is needs_body


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/", "GET"),
        ("/save", "POST"),
        ("/__observe__/feedback", "GET"),
        ("/__observe__/otlp/v1/traces", "GET"),
        ("/__observe__/unknown", "GET"),
    ],
)
def test_route_delegates(core, path, method):
    assert core.route(path, method) is None


def test_shim_reply_is_javascript(core):
    reply = core.reply(core.route("/__observe__/observe.js", "GET"))
    assert reply.status == 200
    assert reply.content_type == JAVASCRIPT
    assert len(reply.body) > 0


def test_config_reply_shape(core):
    reply = core.reply(core.route("/__observe__/config", "GET"))
    assert reply.content_type == JSON
    assert set(json.loads(reply.body)) == {
        "endpoint",
        "feedbackLabel",
        "enrichHook",
        "registerSw",
    }


def test_feedback_pushes_event(core):
    sink = Recorder()
    router.register(sink)
    route = core.route("/__observe__/feedback", "POST")
    core.reply(route, json.dumps({"message": "hi", "user": {"name": "j"}}).encode())
    assert len(sink.feedback) == 1
    assert sink.feedback[0].message == "hi"
    assert sink.feedback[0].user == {"name": "j"}


def test_malformed_json_is_tolerated(core):
    sink = Recorder()
    router.register(sink)
    reply = core.reply(core.route("/__observe__/feedback", "POST"), b"{not json")
    assert reply.status == 200
    assert sink.feedback[0].message == ""


def test_otlp_requires_json_content_type(core):
    sink = Recorder()
    router.register(sink)
    payload = json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [{"name": "s"}]}]}]}).encode()
    route = core.route("/__observe__/otlp/v1/traces", "POST")
    core.reply(route, payload, "text/plain")
    assert sink.errors == []
    core.reply(route, payload, "application/json")
    assert len(sink.errors) == 1


@pytest.mark.parametrize(
    ("path", "binary"),
    [
        ("/logo.png", True),
        ("/font.WOFF2", True),
        ("/index.html", False),
        ("/noextension", False),
        ("/a.png/b", False),
    ],
)
def test_is_binary(core, path, binary):
    assert core.is_binary(path) is binary


@pytest.mark.parametrize(
    ("status", "content_type", "expected"),
    [
        (200, "text/html; charset=utf-8", True),
        (204, "text/html", True),
        (302, "text/html", False),
        (500, "text/html", False),
        (200, "application/json", False),
        (200, "", False),
    ],
)
def test_should_inject(core, status, content_type, expected):
    assert core.should_inject(status, content_type) is expected


def test_inject_after_head(core):
    out = core.inject(b"<html><head><title>t</title></head></html>")
    assert out.index(b"observe.js") > out.index(b"<head>")
    assert out.index(b"observe.js") < out.index(b"<title>")


def test_inject_prepends_when_a_document_has_no_head(core):
    out = core.inject(b"<html><body>bare</body></html>")
    assert out.startswith(b"<script")


@pytest.mark.parametrize(
    "fragment",
    [
        b"<p>bare</p>",
        b'<div id="queue"><table></table></div>',
        b"",
    ],
)
def test_fragments_are_never_injected(core, fragment):
    """htmx swaps this into a page that already has the shim."""
    assert core.inject(fragment) == fragment


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"<!DOCTYPE html><html>", True),
        (b"<html lang='de'>", True),
        (b"<head><title>t</title></head>", True),
        (b"\n  <!doctype html>", True),
        (b"<div>fragment</div>", False),
        (b"<p>x</p>" * 500 + b"<html>", False),
    ],
)
def test_is_document(body, expected):
    from observe.core import is_document

    assert is_document(body) is expected


def test_inject_only_first_head(core):
    assert core.inject(b"<head><head>").count(b"observe.js") == 1


def test_shim_is_cached(core):
    assert core.shim("observe.js") is core.shim("observe.js")


class TestInjectionOrder:
    """The shim is a classic script: it runs as soon as it loads.

    Anything the page must give it has to be in the document before the
    `<script src>` tag, or the shim sees `undefined` and quietly uses its
    defaults — which is what made `register_sw=False` do nothing.
    """

    def test_config_is_set_before_the_shim_is_loaded(self):
        core = ObserveCore(ObserveConfig())
        page = core.inject(b"<!doctype html><html><head></head><body></body></html>")
        assert page.index(b"__OBSERVE_CONFIG__") < page.index(b"observe.js")

    def test_options_reach_the_page(self):
        core = ObserveCore(ObserveConfig(register_sw=False, feedback_label="Sag was"))
        page = core.inject(b"<html><head></head></html>")
        assert b'"registerSw": false' in page
        assert b"Sag was" in page


class TestServiceWorkerScope:
    def test_the_worker_is_allowed_the_whole_origin(self):
        """Served from `__observe__/`, it could otherwise only claim that path."""
        core = ObserveCore(ObserveConfig())
        route = core.route("/__observe__/observe.sw.js", "GET")
        assert route is not None
        assert ("Service-Worker-Allowed", "/") in core.reply(route).headers

    def test_the_ordinary_shim_carries_no_extra_headers(self):
        core = ObserveCore(ObserveConfig())
        route = core.route("/__observe__/observe.js", "GET")
        assert route is not None
        assert core.reply(route).headers == ()


class TestFeedbackShim:
    """The form has to send what a router needs to route on."""

    def test_asks_for_a_category_and_a_name(self):
        shim = ObserveCore(ObserveConfig()).shim("observe.js").decode()
        assert "category: category.value" in shim
        assert "name: who" in shim

    def test_carries_the_user_block_the_server_already_parses(self):
        shim = ObserveCore(ObserveConfig()).shim("observe.js").decode()
        assert "user: user || {}" in shim

    def test_does_not_use_a_browser_prompt(self):
        """A prompt cannot collect a category, and blocks the page."""
        assert "prompt(" not in ObserveCore(ObserveConfig()).shim("observe.js").decode()


class TestDelivery:
    """A submission must not wait on whatever the sinks go and do."""

    def test_the_request_does_not_wait_for_a_slow_sink(self):
        import time

        started = threading.Event()

        class Slow:
            def push_error(self, event): ...

            def push_feedback(self, event):
                started.set()
                time.sleep(2)

        router.background = True
        router.register(Slow())
        core = ObserveCore(ObserveConfig())
        route = core.route("/__observe__/feedback", "POST")
        assert route is not None

        begin = time.monotonic()
        core.reply(route, b'{"message": "hi"}', JSON)
        assert time.monotonic() - begin < 0.5
        assert started.wait(1)
        router.drain()

    def test_one_failing_sink_does_not_stop_the_others(self):
        seen = []

        class Broken:
            def push_error(self, event): ...

            def push_feedback(self, event):
                raise RuntimeError("no")

        class Fine:
            def push_error(self, event): ...

            def push_feedback(self, event):
                seen.append(event.message)

        router.register(Broken())
        router.register(Fine())
        core = ObserveCore(ObserveConfig())
        route = core.route("/__observe__/feedback", "POST")
        assert route is not None
        core.reply(route, b'{"message": "hi"}', JSON)
        assert seen == ["hi"]
