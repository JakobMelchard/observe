"""Transport-agnostic observe request handling.

Every middleware — WSGI, ASGI, ``http.server`` — is a thin adapter over
:class:`ObserveCore`.  The core owns the parts that do not depend on the
transport: which paths belong to observe, what each one replies, which
responses get the browser shim injected, and how OTLP payloads reach the
router.  Adapters own only body reading and response emission.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from importlib.resources import files
from urllib.parse import urlsplit

from observe.config.config import ObserveConfig
from observe.receiver.otlp import otlp_to_errors
from observe.router import router
from observe.sink.sink import FeedbackEvent

PREFIX = "/__observe__/"
JAVASCRIPT = "application/javascript"
JSON = "application/json"

SHIM_DIR = files("observe") / "shim"
SHIMS = ("observe.js", "observe.sw.js")

#: A worker may only claim a scope at or below its own path, unless the
#: response says otherwise. The service worker is served from `__observe__/`
#: but has to see the whole origin to be of any use.
SHIM_HEADERS = {"observe.sw.js": (("Service-Worker-Allowed", "/"),)}

#: A full page announces itself in its opening bytes. The tag name must end
#: there, so `<header>` or a `<heading>` element is not mistaken for `<head>`.
DOCUMENT_MARKERS = re.compile(rb"<(?:!doctype\s+html|html|head)[\s/>]")

#: How far into a response to look for those markers.
MARKER_WINDOW = 1024

BINARY_EXT = frozenset(
    {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "ico",
        "svg",
        "woff",
        "woff2",
        "ttf",
        "eot",
        "pdf",
        "zip",
        "gz",
    }
)


class Kind(StrEnum):
    SHIM = "shim"
    CONFIG = "config"
    FEEDBACK = "feedback"
    OTLP = "otlp"


@dataclass(frozen=True)
class Route:
    """An observe endpoint matched from a request line.

    ``needs_body`` tells the adapter whether to read the request body before
    calling :meth:`ObserveCore.reply` — adapters read bodies differently
    (blocking vs. awaited), so the core never reads one itself.
    """

    kind: Kind
    needs_body: bool
    name: str = ""


@dataclass(frozen=True)
class Reply:
    status: int
    content_type: str
    body: bytes
    #: Anything beyond content-type and length. Rare enough to default empty.
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def status_line(self) -> str:
        return f"{self.status} {HTTPStatus(self.status).phrase}"


#: What a POST gets when an ingest endpoint does not take it.
CROSS_SITE = Reply(403, JSON, b'{"error": "cross-site request"}')
TOO_LARGE = Reply(413, JSON, b'{"error": "body too large"}')
TOO_MANY = Reply(429, JSON, b'{"error": "too many requests"}')

#: Length of a rate-limit window, in seconds.
WINDOW = 60.0


class RateLimit:
    """At most ``limit`` hits per client in each window; 0 lifts the limit.

    One fixed window for all clients. The table is dropped when the window
    turns over, so it cannot grow without bound. Counts live in this process
    only, which is all a single-process server needs.
    """

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self._clock = clock
        self._start = clock()
        self._hits: dict[str, int] = {}
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        if not self.limit:
            return True
        with self._lock:
            now = self._clock()
            if now - self._start >= WINDOW:
                self._start, self._hits = now, {}
            hits = self._hits.get(client, 0)
            if hits >= self.limit:
                return False
            self._hits[client] = hits + 1
            return True


class ObserveCore:
    """Transport-independent half of every observe middleware."""

    def __init__(self, cfg: ObserveConfig) -> None:
        self.cfg = cfg
        # The same bytes are inlined into a <script> below, where a literal
        # "<" could close the element. The escape is still valid JSON.
        self.config_bytes = (
            json.dumps(
                {
                    "endpoint": cfg.endpoint,
                    "feedbackLabel": cfg.feedback_label,
                    "enrichHook": cfg.enrich_hook,
                    "registerSw": cfg.register_sw,
                }
            )
            .replace("<", "\\u003c")
            .encode()
        )
        # Config first. The shim is a classic script, so it runs the moment
        # it loads — before the parser reaches anything after it. Injected the
        # other way round, every option silently fell back to its default.
        self._tag = (
            b"<script>window.__OBSERVE_CONFIG__ = "
            + self.config_bytes
            + b";</script>"
            + b'<script src="/__observe__/observe.js"></script>'
        )
        self._shims: dict[str, bytes] = {}
        self._rates = {
            Kind.FEEDBACK: RateLimit(cfg.feedback_per_minute),
            Kind.OTLP: RateLimit(cfg.otlp_per_minute),
        }

    def shim(self, name: str) -> bytes:
        """Return a shim's bytes, reading it from the package once."""
        if name not in self._shims:
            self._shims[name] = (SHIM_DIR / name).read_bytes()
        return self._shims[name]

    def route(self, path: str, method: str) -> Route | None:
        """Match a request line to an observe endpoint, or ``None`` to delegate."""
        for name in SHIMS:
            if path == PREFIX + name:
                return Route(Kind.SHIM, False, name)
        if path == PREFIX + "config":
            return Route(Kind.CONFIG, False)
        if method == "POST":
            if path == PREFIX + "feedback":
                return Route(Kind.FEEDBACK, True)
            if path.startswith(PREFIX + "otlp"):
                return Route(Kind.OTLP, True)
        return None

    def refuse(self, route: Route, headers: Mapping[str, str], client: str) -> Reply | None:
        """Turn a POST away before its body is read, or ``None`` to take it.

        ``headers`` are the request headers, looked up by lower-case name.
        ``client`` is what the transport knows the peer by, normally its
        address. A refused POST does not count against the rate limit.
        """
        if not route.needs_body:
            return None
        if self.cfg.same_site and _cross_site(headers):
            return CROSS_SITE
        try:
            length = int(headers.get("content-length") or 0)
        except ValueError:
            return TOO_LARGE
        # A negative length would make a transport read to the end of the stream.
        if length < 0 or self._too_large(length):
            return TOO_LARGE
        if not self._rates[route.kind].allow(client):
            return TOO_MANY
        return None

    def _too_large(self, size: int) -> bool:
        return 0 < self.cfg.max_body_bytes < size

    def reply(self, route: Route, body: bytes = b"", content_type: str = "") -> Reply:
        """Produce the response for a matched route, pushing events as a side effect."""
        match route.kind:
            case Kind.SHIM:
                return Reply(
                    200, JAVASCRIPT, self.shim(route.name), SHIM_HEADERS.get(route.name, ())
                )
            case Kind.CONFIG:
                return Reply(200, JSON, self.config_bytes)
            # A body can outgrow the cap without declaring a length up front.
            case _ if self._too_large(len(body)):
                return TOO_LARGE
            case Kind.FEEDBACK:
                self._push_feedback(_loads(body))
            case Kind.OTLP if body and "json" in content_type:
                for event in otlp_to_errors(_loads(body)):
                    router.push_error(event)
        return Reply(200, JSON, b"{}")

    def is_binary(self, path: str) -> bool:
        """True when a path's extension marks it as non-HTML, skipping injection."""
        head, sep, ext = path.rpartition(".")
        return bool(sep) and ext.lower() in BINARY_EXT

    def should_inject(self, status: int, content_type: str) -> bool:
        return 200 <= status < 300 and "text/html" in content_type

    def inject(self, html: bytes) -> bytes:
        """Insert the shim script tags into a full document.

        Partial HTML is returned untouched. Fragment-swapping clients such as
        htmx serve HTML that is spliced into a page that already has the
        shim; injecting there would re-run it on every swap and push script
        tags into fragments that must not contain any.
        """
        if not is_document(html):
            return html
        if b"<head>" in html:
            return html.replace(b"<head>", b"<head>" + self._tag, 1)
        return self._tag + html

    @staticmethod
    def _push_feedback(data: dict[str, object]) -> None:
        router.push_feedback(
            FeedbackEvent(
                message=str(data.get("message", "")),
                timestamp=str(data.get("timestamp", "")),
                context=_as_dict(data.get("context")),
                user={str(k): str(v) for k, v in _as_dict(data.get("user")).items()},
            )
        )


def is_document(html: bytes) -> bool:
    """True when a response is a whole page rather than a fragment."""
    return DOCUMENT_MARKERS.search(html[:MARKER_WINDOW].lower()) is not None


def _cross_site(headers: Mapping[str, str]) -> bool:
    """True when a browser says the request comes from another site.

    Browsers send ``Sec-Fetch-Site`` to HTTPS and localhost only. Over plain
    HTTP the ``Origin`` header is what is left; its host is compared with the
    ``Host`` the request was sent to. A client that sends neither header is
    not a browser and is let through.
    """
    site = headers.get("sec-fetch-site")
    if site:
        return site.lower() == "cross-site"
    origin = headers.get("origin")
    if not origin:
        return False
    try:
        theirs = urlsplit(origin).hostname
        ours = urlsplit("//" + (headers.get("host") or "")).hostname
    except ValueError:
        return True
    return theirs is None or theirs != ours


def _loads(body: bytes) -> dict[str, object]:
    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}
