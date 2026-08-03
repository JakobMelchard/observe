## Skill: observe sinks

### Creating a sink

1. Create package at `sinks/<name>/`
2. `pyproject.toml` with `observe` as dependency
3. Implement `Sink` protocol:

```python
from observe.sink.sink import ErrorEvent, FeedbackEvent

class MySink:
    def push_error(self, event: ErrorEvent) -> None:
        # send to your backend
        pass

    def push_feedback(self, event: FeedbackEvent) -> None:
        pass
```

4. Register: `router.register(MySink())`

### Event shapes

```python
@dataclass
class ErrorEvent:
    message: str
    level: str  # "error" | "warning" | "info"
    timestamp: str
    context: dict[str, Any]
    trace_id: str | None
    span_id: str | None

@dataclass
class FeedbackEvent:
    message: str
    timestamp: str
    context: dict[str, Any]
    user: dict[str, str]  # {"email": "...", "name": "..."}
```

### Sentry reference

See `sinks/sentry/src/observe_sentry/sink.py`:
- `ErrorEvent` → `sentry_sdk.capture_event()` with trace context
- `FeedbackEvent` → `sentry_sdk.capture_user_feedback()`
