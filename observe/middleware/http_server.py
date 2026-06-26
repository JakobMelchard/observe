import io
import json
from importlib.resources import files

from observe import router
from observe.config.config import ObserveConfig
from observe.sink.sink import FeedbackEvent

SHIM_DIR = files("observe") / "shim"


def patch_handler(handler_class, config: ObserveConfig):
    _shims = {}
    config_bytes = json.dumps(
        {
            "endpoint": config.endpoint,
            "feedbackLabel": config.feedback_label,
            "enrichHook": config.enrich_hook,
            "registerSw": config.register_sw,
        }
    ).encode()

    def _load_shim(name):
        if name not in _shims:
            _shims[name] = (SHIM_DIR / name).read_bytes()
        return _shims[name]

    def _is_observe_path(self, path):
        if path == "/__observe__/observe.js":
            body = _load_shim("observe.js")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        if path == "/__observe__/observe.sw.js":
            body = _load_shim("observe.sw.js")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        if path == "/__observe__/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(config_bytes)))
            self.end_headers()
            self.wfile.write(config_bytes)
            return True
        return False

    def _is_observe_post(self_obj, path):
        if path == "/__observe__/feedback":
            length = int(self_obj.headers.get("Content-Length", 0))
            body = self_obj.rfile.read(length) if length else b"{}"
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
            self_obj.send_response(200)
            self_obj.send_header("Content-Type", "application/json")
            self_obj.end_headers()
            self_obj.wfile.write(b"{}")
            return True
        if path.startswith("/__observe__/otlp"):
            length = int(self_obj.headers.get("Content-Length", 0))
            body = self_obj.rfile.read(length) if length else b"{}"
            content_type = self_obj.headers.get("Content-Type", "")
            if body and "json" in content_type:
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    data = {}
                from observe.receiver.otlp import log_to_error, span_to_error

                for rs in data.get("resourceSpans", []):
                    for ss in rs.get("scopeSpans", []):
                        for sp in ss.get("spans", []):
                            router.push_error(span_to_error(sp))
                for rl in data.get("resourceLogs", []):
                    for sl in rl.get("scopeLogs", []):
                        for log in sl.get("logRecords", []):
                            router.push_error(log_to_error(log))
            self_obj.send_response(200)
            self_obj.send_header("Content-Type", "application/json")
            self_obj.end_headers()
            self_obj.wfile.write(b"{}")
            return True
        return False

    class _BufferedWfile(io.RawIOBase):
        def __init__(self, real_wfile):
            self._real = real_wfile
            self._buf = io.BytesIO()

        def writable(self):
            return True

        def write(self, b):
            return self._buf.write(b)

        def flush(self):
            pass

        def close(self):
            pass

        def getvalue(self):
            return self._buf.getvalue()

    def _flush_with_injection(self, buf, headers_sent):
        raw = buf.getvalue()
        idx = raw.find(b"\r\n\r\n")
        if idx == -1:
            self.wfile = buf._real
            self.wfile.write(raw)
            return
        header_bytes = raw[:idx]
        body = raw[idx + 4 :]
        ct = None
        for line in header_bytes.split(b"\r\n"):
            if line.lower().startswith(b"content-type:"):
                ct = line.split(b":", 1)[1].strip().decode()
                break
        if ct and "text/html" in ct:
            tag = (
                b'<script src="/__observe__/observe.js"></script>'
                b"<script>window.__OBSERVE_CONFIG__ = " + config_bytes + b";</script>"
            )
            if b"<head>" in body:
                body = body.replace(b"<head>", b"<head>" + tag, 1)
            else:
                body = tag + body
            new_headers = []
            for line in header_bytes.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    new_headers.append(f"Content-Length: {len(body)}".encode())
                else:
                    new_headers.append(line)
            raw = b"\r\n".join(new_headers) + b"\r\n\r\n" + body
        self.wfile = buf._real
        self.wfile.write(raw)

    orig_do_GET = handler_class.do_GET  # noqa: N806

    def do_GET(self):  # noqa: N802
        if _is_observe_path(self, self.path):
            return
        buf = _BufferedWfile(self.wfile)
        self.wfile = buf
        try:
            orig_do_GET(self)
        finally:
            if buf.getvalue():
                _flush_with_injection(self, buf, True)
            else:
                self.wfile = buf._real

    handler_class.do_GET = do_GET

    orig_do_POST = handler_class.do_POST  # noqa: N806

    def do_POST(self):  # noqa: N802
        from urllib.parse import urlparse

        path = urlparse(self.path).path
        if _is_observe_post(self, path):
            return
        buf = _BufferedWfile(self.wfile)
        self.wfile = buf
        try:
            orig_do_POST(self)
        finally:
            if buf.getvalue():
                _flush_with_injection(self, buf, True)
            else:
                self.wfile = buf._real

    handler_class.do_POST = do_POST
