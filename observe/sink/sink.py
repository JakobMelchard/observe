from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ErrorEvent:
    message: str
    level: str
    timestamp: str
    context: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    span_id: str | None = None


@dataclass
class FeedbackEvent:
    message: str
    timestamp: str
    context: dict[str, Any] = field(default_factory=dict)
    user: dict[str, str] = field(default_factory=dict)


class Sink(Protocol):
    def push_error(self, event: ErrorEvent) -> None: ...
    def push_feedback(self, event: FeedbackEvent) -> None: ...
