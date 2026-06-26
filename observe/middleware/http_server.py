import json
from pathlib import Path

from observe import router
from observe.config.config import ObserveConfig
from observe.sink.sink import FeedbackEvent

SHIM_DIR = Path(__file__).resolve().parent.parent / "shim"


def patch_handler(handler_class, config: ObserveConfig):
    _shims = {}
    config_bytes = json.dumps({
        "endpoint": config.endpoint,
        "feedbackLabel": config.feedback_label,
        "enrichHook": config.enrich_hook,
        "registerSw": config.register_sw,
    }).encode()

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

    def _is_observe_path_post(self, self_obj, path):
        if path == "/__observe__/feedback":
            length = int(self_obj.headers.get("Content-Length", 0))
            body = self_obj.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {}
            router.push_feedback(FeedbackEvent(
                message=data.get("message", ""),
                timestamp=data.get("timestamp", ""),
                context=data.get("context", {}),
                user=data.get("user", {}),
            ))
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

    orig_do_GET = handler_class.do_GET

    def do_GET(self):
        if _is_observe_path(self, self.path):
            return
        orig_do_GET(self)

    handler_class.do_GET = do_GET

    orig_do_POST = handler_class.do_POST

    def do_POST(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        if _is_observe_path_post(self, path):
            return
        orig_do_POST(self)

    handler_class.do_POST = do_POST
