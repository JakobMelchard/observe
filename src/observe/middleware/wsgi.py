"""WSGI adapter for :class:`observe.core.ObserveCore`."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from observe.config.config import ObserveConfig
from observe.core import ObserveCore, Reply

Environ = dict[str, Any]
StartResponse = Callable[..., Any]
WSGIApp = Callable[[Environ, StartResponse], Iterable[bytes]]


class ObserveMiddleware:
    def __init__(self, app: WSGIApp, config: ObserveConfig) -> None:
        self.app = app
        self.cfg = config
        self.core = ObserveCore(config)

    def __call__(self, environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        path = environ["PATH_INFO"]

        route = self.core.route(path, environ["REQUEST_METHOD"])
        if route is not None:
            body = _read(environ) if route.needs_body else b""
            reply = self.core.reply(route, body, environ.get("CONTENT_TYPE", ""))
            return _emit(reply, start_response)

        if self.core.is_binary(path):
            return self.app(environ, start_response)

        status: list[str] = []
        headers: list[tuple[str, str]] = []

        def _capture(code: str, hdrs: list[tuple[str, str]], exc_info: Any = None) -> Any:
            status.append(code)
            headers[:] = hdrs
            return start_response(code, hdrs, exc_info)

        body = b"".join(self.app(environ, _capture))
        code = status[0] if status else "200 OK"
        content_type = next((v for k, v in headers if k.lower() == "content-type"), "")

        if self.core.should_inject(int(code.split(" ", 1)[0]), content_type):
            body = self.core.inject(body)
            headers[:] = [
                (k, str(len(body))) if k.lower() == "content-length" else (k, v) for k, v in headers
            ]

        return [body]


def _read(environ: Environ) -> bytes:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    body: bytes = environ["wsgi.input"].read(length) if length else b""
    return body


def _emit(reply: Reply, start_response: StartResponse) -> list[bytes]:
    headers = [
        ("Content-Type", reply.content_type),
        ("Content-Length", str(len(reply.body))),
    ]
    start_response(f"{reply.status} OK", headers)
    return [reply.body]
