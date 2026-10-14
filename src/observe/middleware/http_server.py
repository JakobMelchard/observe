"""``http.server`` adapter for :class:`observe.core.ObserveCore`.

Patches an existing ``BaseHTTPRequestHandler`` subclass in place.  Handlers
write raw bytes straight to the socket, so injection needs an HTML response
buffered first, which is what :class:`_BufferedWfile` is for. Anything else is
streamed through as soon as its headers are known.
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
        reply = core.refuse(route, handler.headers, handler.client_address[0])
        if reply is not None:
            # The body stays unread, so the connection cannot serve another request.
            handler.close_connection = True
        else:
            body = b""
            if route.needs_body:
                length = int(handler.headers.get("Content-Length", 0))
                body = handler.rfile.read(length) if length else b""
            reply = core.reply(route, body, handler.headers.get("Content-Type", ""))
        _emit(handler, reply)
        return True

    def _wrap(method: str) -> None:
        original = getattr(handler_class, f"do_{method}", None)

        def handle(handler: Any) -> None:
            if _serve(handler, method):
                return
            if original is None:
                # What the base handler answers for a method it does not have.
                handler.send_error(501, f"Unsupported method ({method!r})")
                return
            if core.is_binary(urlparse(handler.path).path):
                original(handler)
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
    for name, value in reply.headers:
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(reply.body)


def _header(lines: list[bytes], name: bytes) -> str:
    for line in lines:
        if line.lower().startswith(name + b":"):
            return line.split(b":", 1)[1].strip().decode()
    return ""


def _is_html(head: bytes) -> bool:
    lines = head.split(b"\r\n")
    return "text/html" in _header(lines, b"content-type") and "chunked" not in _header(
        lines, b"transfer-encoding"
    )


def _inject_raw(core: ObserveCore, raw: bytes) -> bytes:
    """Inject into a buffered raw HTTP response, rewriting Content-Length."""
    head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep or not _is_html(head):
        return raw
    body = core.inject(body)
    lines = [
        f"Content-Length: {len(body)}".encode()
        if line.lower().startswith(b"content-length:")
        else line
        for line in head.split(b"\r\n")
    ]
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


class _BufferedWfile(io.RawIOBase):
    """Holds an HTML response so it can be rewritten; passes anything else straight through."""

    def __init__(self, real: Any) -> None:
        self.real = real
        self._buf = io.BytesIO()
        self._headers_done = False
        self._passthrough = False

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:
        if self._passthrough:
            self.real.write(b)
            return len(b)
        self._buf.write(b)
        if not self._headers_done:
            head, sep, _ = self._buf.getvalue().partition(b"\r\n\r\n")
            if sep:
                self._headers_done = True
                if not _is_html(head):
                    self._passthrough = True
                    self.real.write(self._buf.getvalue())
                    self._buf = io.BytesIO()
        return len(b)

    def flush(self) -> None:
        if self._passthrough:
            self.real.flush()

    def close(self) -> None:
        pass

    def getvalue(self) -> bytes:
        return self._buf.getvalue()
