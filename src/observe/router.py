"""Fan-out from the receiver to whatever sinks are registered.

Delivery happens off the request thread. Sinks reach the network — opening a
GitHub issue, scoring feedback with a local model — and a submission that
waits for all of that leaves the person staring at a spinner for as long as
it takes. Nothing downstream reports back to the browser anyway.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from observe.sink.sink import ErrorEvent, FeedbackEvent, Sink

log = logging.getLogger(__name__)

WORKERS = 2


class Router:
    def __init__(self) -> None:
        self._sinks: list[Sink] = []
        self._pool: ThreadPoolExecutor | None = None
        #: Deliver in the background. Tests set this False so a push is
        #: finished, and assertable, by the time it returns.
        self.background = True

    def register(self, sink: Sink) -> None:
        self._sinks.append(sink)

    def push_error(self, event: ErrorEvent) -> None:
        self._dispatch("push_error", event)

    def push_feedback(self, event: FeedbackEvent) -> None:
        self._dispatch("push_feedback", event)

    def drain(self) -> None:
        """Wait for in-flight deliveries, then start fresh."""
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True)

    def _dispatch(self, method: str, event: Any) -> None:
        for sink in list(self._sinks):
            if self.background:
                self._executor().submit(self._deliver, sink, method, event)
            else:
                self._deliver(sink, method, event)

    def _executor(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="observe-sink")
        return self._pool

    @staticmethod
    def _deliver(sink: Sink, method: str, event: Any) -> None:
        """One sink's failure must not take the others down with it."""
        try:
            getattr(sink, method)(event)
        except Exception:
            log.exception("sink %s failed in %s", type(sink).__name__, method)


router = Router()
