import sentry_sdk

from observe.sink.sink import ErrorEvent, FeedbackEvent


class SentrySink:
    def push_error(self, event: ErrorEvent) -> None:
        sentry_sdk.capture_event(
            {
                "level": event.level,
                "message": {"formatted": event.message},
                "timestamp": _parse_timestamp(event.timestamp),
                "extra": event.context,
                "contexts": {
                    "trace": {
                        "trace_id": event.trace_id or None,
                        "span_id": event.span_id or None,
                    },
                },
            }
        )

    def push_feedback(self, event: FeedbackEvent) -> None:
        sentry_sdk.capture_user_feedback(
            {
                "email": event.user.get("email", ""),
                "name": event.user.get("name", ""),
                "comments": event.message,
            }
        )


def _parse_timestamp(ts: str) -> float | None:
    try:
        return float(ts) / 1e9 if ts and ts.isdigit() else ts
    except (ValueError, TypeError):
        return None
