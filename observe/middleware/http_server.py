"""``http.server`` adapter for :class:`observe.core.ObserveCore`.

Patches an existing ``BaseHTTPRequestHandler`` subclass in place.  Handlers
write raw bytes straight to the socket, so injection needs the response
buffered first — that is what :class:`_BufferedWfile` is for.
"""

from __future__ import annotations

import io
from typing import Any
from urllib.parse import urlparse

from observe.config.config import ObserveConfig
from observe.core import ObserveCore, Reply


def patch_handler(handler_class: type[Any], config: ObserveConfig) -> None:
    """Wrap a handler's ``do_GET``/``do_POST`` with observe routing and injection."""
    core = ObserveCore(config)

    def _serve(handler: Any, method: str) -> bool:
        path = urlparse(handler.path).path
        route = core.route(path, method)
        if route is None:
            return False
        body = b""
        if route.needs_body:
            length = int(handler.headers.get("Content-Length", 0))
            body = handler.rfile.read(length) if length else b""
        _emit(handler, core.reply(route, body, handler.headers.get("Content-Type", "")))
        return True

    def _wrap(method: str) -> None:
        original = getattr(handler_class, f"do_{method}")

        def handle(handler: Any) -> None:
            if _serve(handler, method):
                return
            buf = _BufferedWfile(handler.wfile)
            handler.wfile = buf
            try:
                original(handler)
            finally:
                handler.wfile = buf.real
                raw = buf.getvalue()
                if raw:
                    handler.wfile.write(_inject_raw(core, raw))

        handle.__name__ = f"do_{method}"
        setattr(handler_class, f"do_{method}", handle)

    _wrap("GET")
    _wrap("POST")


def _emit(handler: Any, reply: Reply) -> None:
    handler.send_response(reply.status)
    handler.send_header("Content-Type", reply.content_type)
    handler.send_header("Content-Length", str(len(reply.body)))
    handler.end_headers()
    handler.wfile.write(reply.body)


def _inject_raw(core: ObserveCore, raw: bytes) -> bytes:
    """Inject into a buffered raw HTTP response, rewriting Content-Length."""
    head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep:
        return raw
    lines = head.split(b"\r\n")
    content_type = next(
        (
            line.split(b":", 1)[1].strip().decode()
            for line in lines
            if line.lower().startswith(b"content-type:")
        ),
        "",
    )
    if "text/html" not in content_type:
        return raw
    body = core.inject(body)
    lines = [
        f"Content-Length: {len(body)}".encode()
        if line.lower().startswith(b"content-length:")
        else line
        for line in lines
    ]
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


class _BufferedWfile(io.RawIOBase):
    """Collects handler output so it can be rewritten before hitting the socket."""

    def __init__(self, real: Any) -> None:
        self.real = real
        self._buf = io.BytesIO()

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:
        return self._buf.write(b)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def getvalue(self) -> bytes:
        return self._buf.getvalue()
