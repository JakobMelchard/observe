"""Minimal WSGI app with the observe middleware attached."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any
from wsgiref.simple_server import make_server

from observe.config.config import ObserveConfig
from observe.middleware.wsgi import ObserveMiddleware


def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
    start_response("200 OK", [("Content-Type", "text/html")])
    return [b"<!doctype html><html><head></head><body>Observe demo</body></html>"]


if __name__ == "__main__":
    server = make_server("127.0.0.1", 8000, ObserveMiddleware(app, ObserveConfig()))
    server.serve_forever()
