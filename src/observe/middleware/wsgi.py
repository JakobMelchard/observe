"""WSGI adapter for :class:`observe.core.ObserveCore`."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from itertools import islice
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

        return self._respond(environ, start_response)

    def _respond(self, environ: Environ, start_response: StartResponse) -> Iterator[bytes]:
        """Hold ``start_response`` back until the headers say whether to inject."""
        started: list[tuple[str, list[tuple[str, str]], Any]] = []
        written: list[bytes] = []
        forwarded = False

        def _capture(code: str, hdrs: list[tuple[str, str]], exc_info: Any = None) -> Any:
            if forwarded:
                return start_response(code, hdrs, exc_info)
            started[:] = [(code, hdrs, exc_info)]
            return written.append

        result = self.app(environ, _capture)
        try:
            chunks = iter(result)
            # A generator app calls start_response on its first iteration.
            head = [*islice(chunks, 1)]
            code, headers, exc_info = started[0]
            content_type = next((v for k, v in headers if k.lower() == "content-type"), "")

            if not self.core.should_inject(int(code.split(" ", 1)[0]), content_type):
                forwarded = True
                start_response(code, headers, exc_info)
                yield from (*written, *head)
                yield from chunks
                return

            body = b"".join((*written, *head, *chunks))
            html = self.core.inject(body)
            if html != body:
                headers = [
                    (k, str(len(html))) if k.lower() == "content-length" else (k, v)
                    for k, v in headers
                ]
            start_response(code, headers, exc_info)
            yield html
        finally:
            close = getattr(result, "close", None)
            if close is not None:
                close()


def _read(environ: Environ) -> bytes:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    body: bytes = environ["wsgi.input"].read(length) if length else b""
    return body


def _emit(reply: Reply, start_response: StartResponse) -> list[bytes]:
    headers = [
        ("Content-Type", reply.content_type),
        ("Content-Length", str(len(reply.body))),
        *reply.headers,
    ]
    start_response(f"{reply.status} OK", headers)
    return [reply.body]
