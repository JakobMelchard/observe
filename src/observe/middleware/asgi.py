"""ASGI adapter for :class:`observe.core.ObserveCore`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from observe.config.config import ObserveConfig
from observe.core import ObserveCore, Reply

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class ObserveASGIMiddleware:
    def __init__(self, app: ASGIApp, config: ObserveConfig) -> None:
        self.app = app
        self.cfg = config
        self.core = ObserveCore(config)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        route = self.core.route(path, scope["method"])
        if route is not None:
            body = await _read(receive) if route.needs_body else b""
            await _emit(send, self.core.reply(route, body, _content_type(scope.get("headers", []))))
            return

        if self.core.is_binary(path):
            await self.app(scope, receive, send)
            return

        # Only a response that may be injected is held back; the rest streams.
        held: Message | None = None
        buffer = bytearray()

        async def _intercept(msg: Message) -> None:
            nonlocal held
            if msg["type"] == "http.response.start" and self.core.should_inject(
                msg["status"], _content_type(msg.get("headers", []))
            ):
                held = msg
            elif held is not None and msg["type"] == "http.response.body":
                buffer.extend(msg.get("body", b""))
                if not msg.get("more_body", False):
                    start, held = held, None
                    await self._flush(send, start, bytes(buffer))
            else:
                await send(msg)

        await self.app(scope, receive, _intercept)

    async def _flush(self, send: Send, start: Message, body: bytes) -> None:
        body = self.core.inject(body)
        headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(body)).encode()))
        await send({**start, "headers": headers})
        await send({"type": "http.response.body", "body": body})


def _content_type(headers: list[tuple[bytes, bytes]]) -> str:
    return next((v.decode() for k, v in headers if k.lower() == b"content-type"), "")


async def _read(receive: Receive) -> bytes:
    body = bytearray()
    while True:
        msg = await receive()
        if msg["type"] != "http.request":
            break
        body.extend(msg.get("body", b""))
        if not msg.get("more_body", False):
            break
    return bytes(body)


async def _emit(send: Send, reply: Reply) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": reply.status,
            "headers": [
                (b"content-type", reply.content_type.encode()),
                (b"content-length", str(len(reply.body)).encode()),
                *((k.encode(), v.encode()) for k, v in reply.headers),
            ],
        }
    )
    await send({"type": "http.response.body", "body": reply.body})
