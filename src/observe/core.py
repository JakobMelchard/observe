"""Transport-agnostic observe request handling.

Every middleware — WSGI, ASGI, ``http.server`` — is a thin adapter over
:class:`ObserveCore`.  The core owns the parts that do not depend on the
transport: which paths belong to observe, what each one replies, which
responses get the browser shim injected, and how OTLP payloads reach the
router.  Adapters own only body reading and response emission.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files

from observe.config.config import ObserveConfig
from observe.receiver.otlp import otlp_to_errors
from observe.router import router
from observe.sink.sink import FeedbackEvent

PREFIX = "/__observe__/"
JAVASCRIPT = "application/javascript"
JSON = "application/json"

SHIM_DIR = files("observe") / "shim"
SHIMS = ("observe.js", "observe.sw.js")

#: A full page announces itself in its opening bytes.
DOCUMENT_MARKERS = (b"<!doctype html", b"<html", b"<head")

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


@dataclass(frozen=True)
class Route:
    """An observe endpoint matched from a request line.

    ``needs_body`` tells the adapter whether to read the request body before
    calling :meth:`ObserveCore.reply` — adapters read bodies differently
    (blocking vs. awaited), so the core never reads one itself.
    """

    kind: str
    needs_body: bool
    name: str = ""


@dataclass(frozen=True)
class Reply:
    status: int
    content_type: str
    body: bytes


class ObserveCore:
    """Transport-independent half of every observe middleware."""

    def __init__(self, cfg: ObserveConfig) -> None:
        self.cfg = cfg
        self.config_bytes = json.dumps(
            {
                "endpoint": cfg.endpoint,
                "feedbackLabel": cfg.feedback_label,
                "enrichHook": cfg.enrich_hook,
                "registerSw": cfg.register_sw,
            }
        ).encode()
        self._tag = (
            b'<script src="/__observe__/observe.js"></script>'
            b"<script>window.__OBSERVE_CONFIG__ = " + self.config_bytes + b";</script>"
        )
        self._shims: dict[str, bytes] = {}

    def shim(self, name: str) -> bytes:
        """Return a shim's bytes, reading it from the package once."""
        if name not in self._shims:
            self._shims[name] = (SHIM_DIR / name).read_bytes()
        return self._shims[name]

    def route(self, path: str, method: str) -> Route | None:
        """Match a request line to an observe endpoint, or ``None`` to delegate."""
        for name in SHIMS:
            if path == PREFIX + name:
                return Route("shim", False, name)
        if path == PREFIX + "config":
            return Route("config", False)
        if method == "POST":
            if path == PREFIX + "feedback":
                return Route("feedback", True)
            if path.startswith(PREFIX + "otlp"):
                return Route("otlp", True)
        return None

    def reply(self, route: Route, body: bytes = b"", content_type: str = "") -> Reply:
        """Produce the response for a matched route, pushing events as a side effect."""
        if route.kind == "shim":
            return Reply(200, JAVASCRIPT, self.shim(route.name))
        if route.kind == "config":
            return Reply(200, JSON, self.config_bytes)
        if route.kind == "feedback":
            self._push_feedback(_loads(body))
        elif route.kind == "otlp" and body and "json" in content_type:
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
    head = html[:MARKER_WINDOW].lower()
    return any(marker in head for marker in DOCUMENT_MARKERS)


def _loads(body: bytes) -> dict[str, object]:
    try:
        data = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}
