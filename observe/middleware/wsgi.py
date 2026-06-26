import json
from importlib.resources import files

from observe import router
from observe.config.config import ObserveConfig
from observe.receiver.otlp import log_to_error, span_to_error
from observe.sink.sink import FeedbackEvent

SHIM_DIR = files("observe") / "shim"

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


class ObserveMiddleware:
    def __init__(self, app, config: ObserveConfig):
        self.app = app
        self.cfg = config
        self._shims: dict[str, bytes] = {}
        self._config_bytes = json.dumps(
            {
                "endpoint": self.cfg.endpoint,
                "feedbackLabel": self.cfg.feedback_label,
                "enrichHook": self.cfg.enrich_hook,
                "registerSw": self.cfg.register_sw,
            }
        ).encode()

    def _load_shim(self, name: str) -> bytes:
        if name not in self._shims:
            self._shims[name] = (SHIM_DIR / name).read_bytes()
        return self._shims[name]

    def _shim_response(self, name: str, start_response):
        body = self._load_shim(name)
        headers = [("Content-Type", "application/javascript"), ("Content-Length", str(len(body)))]
        start_response("200 OK", headers)
        return [body]

    def _handle_feedback(self, environ, start_response):
        length = int(environ.get("CONTENT_LENGTH", "0"))
        body = environ["wsgi.input"].read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}
        router.push_feedback(
            FeedbackEvent(
                message=data.get("message", ""),
                timestamp=data.get("timestamp", ""),
                context=data.get("context", {}),
                user=data.get("user", {}),
            )
        )
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b"{}"]

    def _handle_otlp(self, environ, start_response):
        length = int(environ.get("CONTENT_LENGTH", "0"))
        body = environ["wsgi.input"].read(length) if length else b"{}"
        content_type = environ.get("CONTENT_TYPE", "")
        if body and "json" in content_type:
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {}
            for rs in data.get("resourceSpans", []):
                for ss in rs.get("scopeSpans", []):
                    for sp in ss.get("spans", []):
                        router.push_error(span_to_error(sp))
            for rl in data.get("resourceLogs", []):
                for sl in rl.get("scopeLogs", []):
                    for log in sl.get("logRecords", []):
                        router.push_error(log_to_error(log))
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b"{}"]

    def __call__(self, environ, start_response):
        path = environ["PATH_INFO"]
        method = environ["REQUEST_METHOD"]

        if path == "/__observe__/observe.js":
            return self._shim_response("observe.js", start_response)
        if path == "/__observe__/observe.sw.js":
            return self._shim_response("observe.sw.js", start_response)
        if path == "/__observe__/config":
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(self._config_bytes))),
                ],
            )
            return [self._config_bytes]
        if path == "/__observe__/feedback" and method == "POST":
            return self._handle_feedback(environ, start_response)
        if path.startswith("/__observe__/otlp") and method == "POST":
            return self._handle_otlp(environ, start_response)

        parts = path.rsplit(".", 1)
        if len(parts) > 1 and parts[1].lower() in BINARY_EXT:
            return self.app(environ, start_response)

        status_captured = []
        headers_captured = []

        def _start_response(status, headers, exc_info=None):
            status_captured.append(status)
            headers_captured[:] = headers
            return start_response(status, headers, exc_info)

        body_parts = self.app(environ, _start_response)
        body = b"".join(body_parts)

        status = status_captured[0] if status_captured else "200 OK"

        if status.startswith("2") and any(
            k.lower() == "content-type" and "text/html" in v for k, v in headers_captured
        ):
            tag = (
                b'<script src="/__observe__/observe.js"></script>'
                b"<script>window.__OBSERVE_CONFIG__ = " + self._config_bytes + b";</script>"
            )
            if b"<head>" in body:
                body = body.replace(b"<head>", b"<head>" + tag, 1)
            else:
                body = tag + body
            for i, (k, v) in enumerate(list(headers_captured)):
                if k.lower() == "content-length":
                    headers_captured[i] = (k, str(len(body)))
                    break

        return [body]
