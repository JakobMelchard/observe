"""Verify ErrorEvent and FeedbackEvent shapes are compatible with Sentry SDK contract.

Does NOT call Sentry API. Asserts shape only:
- ErrorEvent.message maps to event.message.formatted
- ErrorEvent.level maps to event.level
- ErrorEvent.timestamp maps to event.timestamp (ISO 8601 or Unix ns // Sentry accepts both)
- ErrorEvent.context maps to event.extra
- ErrorEvent.trace_id / span_id map to event.contexts.trace
- FeedbackEvent.message maps to user feedback comments
- FeedbackEvent.user maps to user feedback email/name
"""

import json

import pytest
from werkzeug.test import Client

from observe import router
from observe.config.config import ObserveConfig
from observe.middleware.wsgi import ObserveMiddleware
from observe.sink.sink import ErrorEvent, FeedbackEvent
from tests.fixture import app as fixture_app


class RecordingSink:
    def __init__(self):
        self.errors: list[ErrorEvent] = []
        self.feedback: list[FeedbackEvent] = []

    def push_error(self, event: ErrorEvent) -> None:
        self.errors.append(event)

    def push_feedback(self, event: FeedbackEvent) -> None:
        self.feedback.append(event)


@pytest.fixture(autouse=True)
def reset_router():
    router._sinks.clear()
    router.background = False
    yield


@pytest.fixture
def sink():
    s = RecordingSink()
    router.register(s)
    return s


@pytest.fixture
def client(sink):
    cfg = ObserveConfig()
    wrapped = ObserveMiddleware(fixture_app.app, cfg)
    return Client(wrapped)


class TestSentryErrorShape:
    def test_message_maps_to_sentry_value(self, client, sink):
        client.post(
            "/__observe__/otlp/v1/traces",
            data=json.dumps(
                {
                    "resourceSpans": [
                        {
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "name": "TypeError: undefined is not a function",
                                            "traceId": "abc123",
                                            "spanId": "def456",
                                            "startTimeUnixNano": "1700000000000000000",
                                            "endTimeUnixNano": "1700000000000000000",
                                            "attributes": [
                                                {"key": "level", "value": {"stringValue": "error"}}
                                            ],
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            ),
            content_type="application/json",
        )
        assert len(sink.errors) == 1
        event = sink.errors[0]
        assert event.message == "TypeError: undefined is not a function"

    def test_level_is_valid_sentry_level(self, client, sink):
        for level in ("error", "warning", "info"):
            router._sinks.clear()
            router.register(sink)
            sink.errors.clear()
            client.post(
                "/__observe__/otlp/v1/traces",
                data=json.dumps(
                    {
                        "resourceSpans": [
                            {
                                "scopeSpans": [
                                    {
                                        "spans": [
                                            {
                                                "name": "test",
                                                "startTimeUnixNano": "1",
                                                "endTimeUnixNano": "2",
                                                "attributes": [
                                                    {
                                                        "key": "level",
                                                        "value": {"stringValue": level},
                                                    }
                                                ],
                                            }
                                        ]
                                    }
                                ]
                            }
                        ],
                    }
                ),
                content_type="application/json",
            )
            assert sink.errors[0].level == level

    def test_context_maps_to_sentry_extra(self, client, sink):
        client.post(
            "/__observe__/otlp/v1/traces",
            data=json.dumps(
                {
                    "resourceSpans": [
                        {
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "name": "test",
                                            "startTimeUnixNano": "1",
                                            "endTimeUnixNano": "2",
                                            "attributes": [
                                                {"key": "level", "value": {"stringValue": "error"}},
                                                {
                                                    "key": "url",
                                                    "value": {"stringValue": "/api/fail"},
                                                },
                                                {"key": "status", "value": {"intValue": "500"}},
                                            ],
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            ),
            content_type="application/json",
        )
        event = sink.errors[0]
        assert event.context["url"] == "/api/fail"
        assert event.context["status"] == 500

    def test_trace_id_and_span_id_present(self, client, sink):
        client.post(
            "/__observe__/otlp/v1/traces",
            data=json.dumps(
                {
                    "resourceSpans": [
                        {
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "name": "test",
                                            "startTimeUnixNano": "1",
                                            "endTimeUnixNano": "2",
                                            "traceId": "abc123def456",
                                            "spanId": "789ghi",
                                            "attributes": [
                                                {"key": "level", "value": {"stringValue": "error"}}
                                            ],
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            ),
            content_type="application/json",
        )
        event = sink.errors[0]
        assert event.trace_id == "abc123def456"
        assert event.span_id == "789ghi"

    def test_timestamp_is_iso_or_unix_ns(self, client, sink):
        client.post(
            "/__observe__/otlp/v1/traces",
            data=json.dumps(
                {
                    "resourceSpans": [
                        {
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "name": "test",
                                            "startTimeUnixNano": "1700000000000000000",
                                            "endTimeUnixNano": "1700000000000000000",
                                            "attributes": [
                                                {"key": "level", "value": {"stringValue": "error"}}
                                            ],
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            ),
            content_type="application/json",
        )
        assert sink.errors[0].timestamp == "1700000000000000000"


class TestSentryFeedbackShape:
    def test_message_is_not_empty(self, client, sink):
        client.post(
            "/__observe__/feedback",
            data=json.dumps(
                {
                    "message": "Love this app!",
                    "timestamp": "2025-06-26T12:00:00Z",
                }
            ),
            content_type="application/json",
        )
        assert len(sink.feedback) == 1
        assert sink.feedback[0].message == "Love this app!"

    def test_user_fields_are_strings(self, client, sink):
        client.post(
            "/__observe__/feedback",
            data=json.dumps(
                {
                    "message": "test",
                    "timestamp": "2025-01-01T00:00:00Z",
                    "user": {"email": "user@example.com", "name": "Test User"},
                }
            ),
            content_type="application/json",
        )
        event = sink.feedback[0]
        assert isinstance(event.user["email"], str)
        assert isinstance(event.user["name"], str)
