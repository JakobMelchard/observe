import json
from pathlib import Path

from observe import router
from observe.config.config import ObserveConfig
from observe.receiver.otlp import log_to_error, span_to_error
from observe.sink.sink import FeedbackEvent

SHIM_DIR = Path(__file__).resolve().parent.parent / "shim"
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


class ObserveASGIMiddleware:
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

    async def _read_body(self, receive) -> bytes:
        body = b""
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.request":
                chunk = msg.get("body", b"")
                if chunk:
                    body += chunk
                more = msg.get("more_body", False)
        return body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope["path"]
        method = scope["method"]

        if path == "/__observe__/observe.js":
            return await self._raw_response(
                send,
                200,
                [("content-type", "application/javascript")],
                self._load_shim("observe.js"),
            )
        if path == "/__observe__/observe.sw.js":
            return await self._raw_response(
                send,
                200,
                [("content-type", "application/javascript")],
                self._load_shim("observe.sw.js"),
            )
        if path == "/__observe__/config":
            return await self._raw_response(
                send, 200, [("content-type", "application/json")], self._config_bytes
            )
        if path == "/__observe__/feedback" and method == "POST":
            return await self._handle_feedback(send, receive)
        if path.startswith("/__observe__/otlp") and method == "POST":
            return await self._handle_otlp(send, receive)

        parts = path.rsplit(".", 1)
        if len(parts) > 1 and parts[1].lower() in BINARY_EXT:
            return await self.app(scope, receive, send)

        resp_status = None
        resp_headers = None
        body_buffer = bytearray()

        async def _intercept(msg):
            nonlocal resp_status, resp_headers
            if msg["type"] == "http.response.start":
                resp_status = msg["status"]
                resp_headers = msg.get("headers", [])
            elif msg["type"] == "http.response.body":
                chunk = msg.get("body", b"")
                if chunk:
                    body_buffer.extend(chunk)
                if not msg.get("more_body", False):
                    await self._flush(send, resp_status, resp_headers, bytes(body_buffer))

        await self.app(scope, receive, _intercept)

    async def _flush(self, send, status, headers, body):
        ct = next((v for k, v in (headers or []) if k.lower() == b"content-type"), b"").decode()
        if status is not None and 200 <= status < 300 and "text/html" in ct:
            tag = (
                b'<script src="/__observe__/observe.js"></script>'
                b"<script>window.__OBSERVE_CONFIG__ = " + self._config_bytes + b";</script>"
            )
            if b"<head>" in body:
                body = body.replace(b"<head>", b"<head>" + tag, 1)
            else:
                body = tag + body
            headers = [(k, v) for k, v in (headers or []) if k.lower() != b"content-length"] + [
                (b"content-length", str(len(body)).encode())
            ]
        encoded = [
            (k.encode() if isinstance(k, str) else k, v.encode() if isinstance(v, str) else v)
            for k, v in (headers or [])
        ]
        await send({"type": "http.response.start", "status": status or 200, "headers": encoded})
        await send({"type": "http.response.body", "body": body})

    async def _raw_response(self, send, status, headers, body):
        encoded = [
            (k.encode() if isinstance(k, str) else k, v.encode() if isinstance(v, str) else v)
            for k, v in headers
        ]
        await send({"type": "http.response.start", "status": status, "headers": encoded})
        await send({"type": "http.response.body", "body": body})

    async def _handle_feedback(self, send, receive):
        body = await self._read_body(receive) or b"{}"
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
        await self._raw_response(send, 200, [("content-type", "application/json")], b"{}")

    async def _handle_otlp(self, send, receive):
        body = await self._read_body(receive)
        if body:
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
        await self._raw_response(send, 200, [("content-type", "application/json")], b"{}")
