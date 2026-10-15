"""Unit tests for the transport-agnostic core shared by every middleware."""

import importlib
import json
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Never

import pytest

from observe import ErrorEvent, FeedbackEvent, router
from observe.config.config import ObserveConfig, load_config
from observe.core import DAY, JAVASCRIPT, JSON, ObserveCore, RateLimit, Reply, Route
from observe.router import Router

# The package re-exports the router instance under the module's name.
router_module = importlib.import_module("observe.router")


@pytest.fixture(autouse=True)
def reset_router() -> Iterator[None]:
    router._sinks.clear()
    router.background = False
    yield


@pytest.fixture
def core() -> ObserveCore:
    return ObserveCore(ObserveConfig())


def must_route(core: ObserveCore, path: str, method: str) -> Route:
    route = core.route(path, method)
    assert route is not None
    return route


class Recorder:
    def __init__(self) -> None:
        self.errors: list[ErrorEvent] = []
        self.feedback: list[FeedbackEvent] = []

    def push_error(self, event: ErrorEvent) -> None:
        self.errors.append(event)

    def push_feedback(self, event: FeedbackEvent) -> None:
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
def test_route_matches(
    core: ObserveCore, path: str, method: str, kind: str, needs_body: bool
) -> None:
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
def test_route_delegates(core: ObserveCore, path: str, method: str) -> None:
    assert core.route(path, method) is None


def test_shim_reply_is_javascript(core: ObserveCore) -> None:
    reply = core.reply(must_route(core, "/__observe__/observe.js", "GET"))
    assert reply.status == 200
    assert reply.content_type == JAVASCRIPT
    assert len(reply.body) > 0


def test_config_reply_shape(core: ObserveCore) -> None:
    reply = core.reply(must_route(core, "/__observe__/config", "GET"))
    assert reply.content_type == JSON
    assert set(json.loads(reply.body)) == {
        "endpoint",
        "feedbackLabel",
        "enrichHook",
        "registerSw",
        "button",
    }


def test_feedback_pushes_event(core: ObserveCore) -> None:
    sink = Recorder()
    router.register(sink)
    route = must_route(core, "/__observe__/feedback", "POST")
    core.reply(route, json.dumps({"message": "hi", "user": {"name": "j"}}).encode())
    assert len(sink.feedback) == 1
    assert sink.feedback[0].message == "hi"
    assert sink.feedback[0].user == {"name": "j"}


def test_malformed_json_is_tolerated(core: ObserveCore) -> None:
    sink = Recorder()
    router.register(sink)
    reply = core.reply(must_route(core, "/__observe__/feedback", "POST"), b"{not json")
    assert reply.status == 200
    assert sink.feedback[0].message == ""


def test_otlp_requires_json_content_type(core: ObserveCore) -> None:
    sink = Recorder()
    router.register(sink)
    payload = json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [{"name": "s"}]}]}]}).encode()
    route = must_route(core, "/__observe__/otlp/v1/traces", "POST")
    core.reply(route, payload, "text/plain")
    assert sink.errors == []
    core.reply(route, payload, "application/json")
    assert len(sink.errors) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"resourceSpans": "x"},
        {"resourceSpans": [1]},
        {"resourceSpans": [{"scopeSpans": "x"}]},
        {"resourceSpans": [{"scopeSpans": [{"spans": [None]}]}]},
        {"resourceLogs": [{"scopeLogs": [{"logRecords": "x"}]}]},
    ],
)
def test_malformed_otlp_is_skipped(
    core: ObserveCore,
    payload: dict[str, object],
) -> None:
    sink = Recorder()
    router.register(sink)
    reply = core.reply(
        must_route(core, OTLP, "POST"), json.dumps(payload).encode(), "application/json"
    )
    assert reply.status == 200
    assert sink.errors == []


def test_malformed_otlp_attributes_are_dropped_and_the_span_kept(core: ObserveCore) -> None:
    sink = Recorder()
    router.register(sink)
    attrs = [
        7,
        {"key": "a", "value": "x"},
        {"key": ["a"], "value": {"stringValue": "x"}},
        {"key": {"a": 1}, "value": {"stringValue": "x"}},
        {"key": "n", "value": {"intValue": "abc"}},
        {"key": "big", "value": {"intValue": float("inf")}},
        {"key": "ok", "value": {"intValue": "3"}},
    ]
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": [{"name": "s", "attributes": attrs}]}]}]}
    core.reply(must_route(core, OTLP, "POST"), json.dumps(payload).encode(), "application/json")
    assert [e.context for e in sink.errors] == [{"ok": 3}]


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
def test_is_binary(core: ObserveCore, path: str, binary: bool) -> None:
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
def test_should_inject(core: ObserveCore, status: int, content_type: str, expected: bool) -> None:
    assert core.should_inject(status, content_type) is expected


def test_inject_after_head(core: ObserveCore) -> None:
    out = core.inject(b"<html><head><title>t</title></head></html>")
    assert out.index(b"observe.js") > out.index(b"<head>")
    assert out.index(b"observe.js") < out.index(b"<title>")


@pytest.mark.parametrize(
    ("page", "after"),
    [
        (b'<!doctype html><html><head lang="en"><title>t</title>', b'<head lang="en">'),
        (b"<!DOCTYPE html><HTML><HEAD><title>t</title>", b"<HEAD>"),
        (b'<!doctype html><html lang="en"><body>bare</body></html>', b'<html lang="en">'),
        (b"<!doctype html><body>bare</body>", b"<!doctype html>"),
    ],
)
def test_inject_keeps_the_doctype_first(core: ObserveCore, page: bytes, after: bytes) -> None:
    out = core.inject(page)
    assert out.startswith(page[:1] + b"!")
    assert out.index(b"observe.js") > out.index(after)
    assert out.count(b"observe.js") == 1


@pytest.mark.parametrize(
    "fragment",
    [
        b"<p>bare</p>",
        b'<div id="queue"><table></table></div>',
        b"<div><header>x</header></div>",
        b"",
    ],
)
def test_fragments_are_never_injected(core: ObserveCore, fragment: bytes) -> None:
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
        (b"<HEAD>", True),
        (b"<head\n>", True),
        (b"<head/>", True),
        (b"<div><header>x</header></div>", False),
        (b"<HEADER class='top'>x</HEADER>", False),
        (b"<heading-title>x</heading-title>", False),
        (b"<html-viewer></html-viewer>", False),
    ],
)
def test_is_document(body: bytes, expected: bool) -> None:
    from observe.core import is_document

    assert is_document(body) is expected


def test_inject_only_first_head(core: ObserveCore) -> None:
    assert core.inject(b"<head><head>").count(b"observe.js") == 1


def test_shim_is_cached(core: ObserveCore) -> None:
    assert core.shim("observe.js") is core.shim("observe.js")


class TestInjectionOrder:
    """The shim is a classic script: it runs as soon as it loads.

    Anything the page must give it has to be in the document before the
    `<script src>` tag, or the shim sees `undefined` and quietly uses its
    defaults, so an option like `register_sw=False` does nothing.
    """

    def test_config_is_set_before_the_shim_is_loaded(self) -> None:
        core = ObserveCore(ObserveConfig())
        page = core.inject(b"<!doctype html><html><head></head><body></body></html>")
        assert page.index(b"__OBSERVE_CONFIG__") < page.index(b"observe.js")

    def test_options_reach_the_page(self) -> None:
        core = ObserveCore(ObserveConfig(register_sw=True, button=False, feedback_label="Sag was"))
        page = core.inject(b"<html><head></head></html>")
        assert b'"registerSw": true' in page
        assert b'"button": false' in page
        assert b"Sag was" in page


def test_the_worker_is_not_registered_by_default() -> None:
    assert ObserveConfig().register_sw is False
    assert b'"registerSw": false' in ObserveCore(ObserveConfig()).config_bytes


class TestServiceWorkerScope:
    def test_the_worker_is_allowed_the_whole_origin(self) -> None:
        """Served from `__observe__/`, it could otherwise only claim that path."""
        core = ObserveCore(ObserveConfig())
        route = core.route("/__observe__/observe.sw.js", "GET")
        assert route is not None
        assert ("Service-Worker-Allowed", "/") in core.reply(route).headers

    def test_the_ordinary_shim_carries_no_extra_headers(self) -> None:
        core = ObserveCore(ObserveConfig())
        route = core.route("/__observe__/observe.js", "GET")
        assert route is not None
        assert core.reply(route).headers == ()


class TestFeedbackShim:
    """The form has to send what a router needs to route on."""

    def test_asks_for_a_category_and_a_name(self) -> None:
        shim = ObserveCore(ObserveConfig()).shim("observe.js").decode()
        assert "category: category.value" in shim
        assert "name: who" in shim

    def test_carries_the_user_block_the_server_already_parses(self) -> None:
        shim = ObserveCore(ObserveConfig()).shim("observe.js").decode()
        assert "user: user || {}" in shim

    def test_does_not_use_a_browser_prompt(self) -> None:
        """A prompt cannot collect a category, and blocks the page."""
        assert "prompt(" not in ObserveCore(ObserveConfig()).shim("observe.js").decode()


class TestDelivery:
    """A submission must not wait on whatever the sinks go and do."""

    def test_the_request_does_not_wait_for_a_slow_sink(self) -> None:
        import time

        started = threading.Event()

        class Slow:
            def push_error(self, event: ErrorEvent) -> None: ...

            def push_feedback(self, event: FeedbackEvent) -> None:
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

    def test_one_failing_sink_does_not_stop_the_others(self) -> None:
        seen: list[str] = []

        class Broken:
            def push_error(self, event: ErrorEvent) -> None: ...

            def push_feedback(self, event: FeedbackEvent) -> Never:
                raise RuntimeError("no")

        class Fine:
            def push_error(self, event: ErrorEvent) -> None: ...

            def push_feedback(self, event: FeedbackEvent) -> None:
                seen.append(event.message)

        router.register(Broken())
        router.register(Fine())
        core = ObserveCore(ObserveConfig())
        route = core.route("/__observe__/feedback", "POST")
        assert route is not None
        core.reply(route, b'{"message": "hi"}', JSON)
        assert seen == ["hi"]


class Blocked:
    """A sink that holds every delivery until released."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.seen: list[str] = []

    def push_error(self, event: ErrorEvent) -> None: ...

    def push_feedback(self, event: FeedbackEvent) -> None:
        self.release.wait(5)
        self.seen.append(event.message)


class TestQueue:
    def test_deliveries_beyond_the_bound_are_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(router_module, "MAX_PENDING", 3)
        r = Router()
        sink = Blocked()
        r.register(sink)
        for n in range(10):
            r.push_feedback(FeedbackEvent(message=str(n), timestamp=""))
        sink.release.set()
        r.drain()
        assert sorted(sink.seen) == ["0", "1", "2"]

    def test_a_finished_delivery_frees_its_slot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(router_module, "MAX_PENDING", 1)
        r = Router()
        sink = Recorder()
        r.register(sink)
        for n in range(3):
            r.push_feedback(FeedbackEvent(message=str(n), timestamp=""))
            r.drain()
        assert [e.message for e in sink.feedback] == ["0", "1", "2"]

    def test_concurrent_pushes_share_one_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        made: list[ThreadPoolExecutor] = []

        class SlowPool(ThreadPoolExecutor):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                made.append(self)
                time.sleep(0.05)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(router_module, "ThreadPoolExecutor", SlowPool)
        r = Router()
        r.register(Recorder())
        threads = [
            threading.Thread(target=r.push_feedback, args=(FeedbackEvent("x", ""),))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        r.drain()
        assert len(made) == 1


class TestInlineConfig:
    """The config is inlined into a `<script>`; a `<` in it must not end the element."""

    def test_markup_in_a_config_value_is_escaped(self) -> None:
        label = "</script><script>alert(1)</script>"
        core = ObserveCore(ObserveConfig(feedback_label=label))
        page = core.inject(b"<html><head></head></html>")
        assert page.count(b"</script>") == 2
        assert json.loads(core.config_bytes)["feedbackLabel"] == label


FEEDBACK = "/__observe__/feedback"
OTLP = "/__observe__/otlp/v1/traces"


#: What a browser sends with a same-origin fetch POST.
BROWSER = {"origin": "http://app.test", "host": "app.test"}


def refuse(
    core: ObserveCore,
    path: str = FEEDBACK,
    headers: dict[str, str] | None = None,
    client: str = "10.0.0.1",
) -> Reply | None:
    route = core.route(path, "POST")
    assert route is not None
    return core.refuse(route, {"content-length": "2", **BROWSER, **(headers or {})}, client)


class TestBodyLimit:
    def test_a_declared_length_over_the_cap_is_refused(self) -> None:
        core = ObserveCore(ObserveConfig(max_body_bytes=10))
        assert refuse(core, headers={"content-length": "10"}) is None
        reply = refuse(core, headers={"content-length": "11"})
        assert reply is not None
        assert reply.status == 413

    @pytest.mark.parametrize("length", ["-1", "abc", "1e3"])
    def test_a_length_that_is_not_a_count_is_refused(self, core: ObserveCore, length: str) -> None:
        reply = refuse(core, headers={"content-length": length})
        assert reply is not None
        assert reply.status == 413

    def test_a_body_over_the_cap_is_not_ingested(self) -> None:
        sink = Recorder()
        router.register(sink)
        core = ObserveCore(ObserveConfig(max_body_bytes=10))
        route = core.route(FEEDBACK, "POST")
        assert route is not None
        reply = core.reply(route, b'{"message": "longer than ten bytes"}', JSON)
        assert reply.status == 413
        assert sink.feedback == []

    def test_zero_lifts_the_cap(self) -> None:
        core = ObserveCore(ObserveConfig(max_body_bytes=0))
        assert refuse(core, headers={"content-length": "99999999"}) is None

    def test_get_routes_are_never_refused(self, core: ObserveCore) -> None:
        route = core.route("/__observe__/config", "GET")
        assert route is not None
        assert core.refuse(route, {"sec-fetch-site": "cross-site"}, "10.0.0.1") is None


class TestSameSite:
    @pytest.mark.parametrize(
        "headers",
        [
            {"sec-fetch-site": "same-origin"},
            {"sec-fetch-site": "same-site"},
            {"sec-fetch-site": "none"},
            # Sec-Fetch-Site wins when a browser sends both.
            {"sec-fetch-site": "same-origin", "origin": "https://other.test", "host": "app.test"},
            {"origin": "http://app.test:8000", "host": "app.test:8000"},
            {"origin": "http://APP.test", "host": "app.test"},
            {"origin": "http://[::1]:8000", "host": "[::1]:8000"},
        ],
    )
    def test_same_site_posts_pass(self, core: ObserveCore, headers: dict[str, str]) -> None:
        assert refuse(core, headers=headers) is None

    def test_feedback_without_a_browser_header_is_refused(self, core: ObserveCore) -> None:
        route = core.route(FEEDBACK, "POST")
        assert route is not None
        reply = core.refuse(route, {"content-length": "2"}, "10.0.0.1")
        assert reply is not None
        assert reply.status == 403

    def test_otlp_without_a_browser_header_passes(self, core: ObserveCore) -> None:
        route = core.route(OTLP, "POST")
        assert route is not None
        assert core.refuse(route, {"content-length": "2"}, "10.0.0.1") is None

    @pytest.mark.parametrize(
        "headers",
        [
            {"sec-fetch-site": "cross-site"},
            {"sec-fetch-site": "cross-site", "origin": "http://app.test", "host": "app.test"},
            {"origin": "https://other.test", "host": "app.test"},
            {"origin": "null", "host": "app.test"},
            {"origin": "null"},
            {"origin": "http://[bad", "host": "app.test"},
        ],
    )
    def test_cross_site_posts_are_refused(self, core: ObserveCore, headers: dict[str, str]) -> None:
        reply = refuse(core, headers=headers)
        assert reply is not None
        assert reply.status == 403

    def test_the_check_can_be_switched_off(self) -> None:
        core = ObserveCore(ObserveConfig(same_site=False))
        assert refuse(core, headers={"sec-fetch-site": "cross-site"}) is None
        route = core.route(FEEDBACK, "POST")
        assert route is not None
        assert core.refuse(route, {}, "10.0.0.1") is None


class TestRateLimit:
    def test_posts_beyond_the_limit_are_refused(self) -> None:
        core = ObserveCore(ObserveConfig(feedback_per_minute=2))
        assert refuse(core) is None
        assert refuse(core) is None
        reply = refuse(core)
        assert reply is not None
        assert reply.status == 429

    def test_each_client_has_its_own_budget(self) -> None:
        core = ObserveCore(ObserveConfig(feedback_per_minute=1))
        assert refuse(core, client="10.0.0.1") is None
        assert refuse(core, client="10.0.0.2") is None
        assert refuse(core, client="10.0.0.1") is not None

    def test_feedback_and_otlp_are_counted_apart(self) -> None:
        core = ObserveCore(ObserveConfig(feedback_per_minute=1, otlp_per_minute=1))
        assert refuse(core, FEEDBACK) is None
        assert refuse(core, OTLP) is None
        assert refuse(core, FEEDBACK) is not None
        assert refuse(core, OTLP) is not None

    def test_a_refused_post_does_not_use_up_the_budget(self) -> None:
        core = ObserveCore(ObserveConfig(feedback_per_minute=1))
        assert refuse(core, headers={"sec-fetch-site": "cross-site"}) is not None
        assert refuse(core) is None

    def test_zero_lifts_the_limit(self) -> None:
        core = ObserveCore(ObserveConfig(feedback_per_minute=0))
        assert all(refuse(core) is None for _ in range(50))

    def test_feedback_has_a_daily_cap_across_all_clients(self) -> None:
        core = ObserveCore(ObserveConfig(feedback_per_day=2))
        assert refuse(core, client="10.0.0.1") is None
        assert refuse(core, client="10.0.0.2") is None
        reply = refuse(core, client="10.0.0.3")
        assert reply is not None
        assert reply.status == 429
        assert refuse(core, OTLP, client="10.0.0.3") is None

    def test_a_client_over_its_limit_does_not_use_up_the_daily_cap(self) -> None:
        core = ObserveCore(ObserveConfig(feedback_per_minute=1, feedback_per_day=2))
        assert refuse(core, client="10.0.0.1") is None
        assert all(refuse(core, client="10.0.0.1") is not None for _ in range(5))
        assert refuse(core, client="10.0.0.2") is None

    def test_the_daily_cap_resets_after_a_day(self) -> None:
        now = [0.0]
        limit = RateLimit(1, window=DAY, clock=lambda: now[0])
        assert limit.allow("")
        now[0] = DAY - 1
        assert not limit.allow("")
        now[0] = DAY
        assert limit.allow("")

    def test_the_budget_comes_back_when_the_window_turns(self) -> None:
        now = [0.0]
        limit = RateLimit(1, clock=lambda: now[0])
        assert limit.allow("a")
        assert not limit.allow("a")
        now[0] = 59.0
        assert not limit.allow("a")
        now[0] = 60.0
        assert limit.allow("a")


def test_limits_load_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "observe.toml"
    path.write_text(
        "[collector]\n"
        "max_body_bytes = 2048\n"
        "same_site = false\n"
        "feedback_per_minute = 3\n"
        "feedback_per_day = 7\n"
        "otlp_per_minute = 0\n"
    )
    cfg = load_config(path)
    assert cfg.max_body_bytes == 2048
    assert cfg.same_site is False
    assert cfg.feedback_per_minute == 3
    assert cfg.feedback_per_day == 7
    assert cfg.otlp_per_minute == 0


def test_discovery_falls_back_from_observe_toml_to_pyproject_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_config().feedback_per_minute == 10
    (tmp_path / "pyproject.toml").write_text("[tool.observe.collector]\nfeedback_per_minute = 3\n")
    assert load_config().feedback_per_minute == 3
    (tmp_path / "observe.toml").write_text("[collector]\nfeedback_per_minute = 5\n")
    assert load_config().feedback_per_minute == 5


def test_pyproject_ignores_top_level_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[collector]\nfeedback_per_minute = 3\n")
    assert load_config().feedback_per_minute == 10
