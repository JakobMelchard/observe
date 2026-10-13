"""SentrySink maps ErrorEvent onto the event dict Sentry's SDK takes.

Does NOT call Sentry API: a stand-in for sentry_sdk records the calls.
FeedbackEvent is not forwarded: the SDK has no feedback API.
"""

import importlib
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from observe.sink.sink import ErrorEvent, FeedbackEvent


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The SDK need not be installed here."""
    sdk = MagicMock()
    monkeypatch.setitem(sys.modules, "sentry_sdk", sdk)
    monkeypatch.setattr(importlib.import_module("observe_sentry.sink"), "sentry_sdk", sdk)
    return sdk


def push(sdk: MagicMock, **fields: Any) -> Any:
    event = {
        "message": "boom",
        "level": "error",
        "timestamp": "1700000000000000000",
        "context": {},
        **fields,
    }
    importlib.import_module("observe_sentry.sink").SentrySink().push_error(ErrorEvent(**event))
    sdk.capture_event.assert_called_once()
    return sdk.capture_event.call_args.args[0]


class TestSentryErrorShape:
    def test_fields_map_to_the_sentry_event(self, sdk: MagicMock) -> None:
        sent = push(
            sdk,
            message="TypeError: undefined is not a function",
            level="warning",
            context={"url": "/api/fail", "status": 500},
            trace_id="abc123",
            span_id="def456",
        )
        assert sent == {
            "level": "warning",
            "message": {"formatted": "TypeError: undefined is not a function"},
            "timestamp": 1700000000.0,
            "extra": {"url": "/api/fail", "status": 500},
            "contexts": {"trace": {"trace_id": "abc123", "span_id": "def456"}},
        }

    def test_missing_trace_ids_are_none(self, sdk: MagicMock) -> None:
        sent = push(sdk)
        assert sent["contexts"] == {"trace": {"trace_id": None, "span_id": None}}

    @pytest.mark.parametrize(
        ("ts", "expected"),
        [
            ("1700000000000000000", 1700000000.0),
            ("2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            ("", None),
        ],
    )
    def test_timestamp(self, sdk: MagicMock, ts: str, expected: object) -> None:
        assert push(sdk, timestamp=ts)["timestamp"] == expected


class TestSentryFeedbackIsNotForwarded:
    def test_the_sink_calls_nothing(self, sdk: MagicMock) -> None:
        module = importlib.import_module("observe_sentry.sink")
        module.SentrySink().push_feedback(
            FeedbackEvent(message="hi", timestamp="2025-01-01T00:00:00Z", context={}, user={})
        )
        assert not sdk.method_calls
