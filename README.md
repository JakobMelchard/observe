# observe

Deployment-agnostic observability sidecar. Instrument Python/Go/JS apps with zero config — injects error tracking, user feedback, and OTLP telemetry via middleware.

## Quickstart

```sh
pip install observe
```

Wrap your app:

```python
from observe import router
from observe.config.config import ObserveConfig
from observe.middleware.wsgi import ObserveMiddleware
from observe_sentry import SentrySink

cfg = ObserveConfig()
router.register(SentrySink())
app = ObserveMiddleware(my_wsgi_app, cfg)
```

Configure via `observe.toml`:

```toml
[observe]
profile = "relay"

[collector]
endpoint = "/__observe__/otlp"

[frontend]
feedback_label = "Feedback"
enrich_hook = "__observe_enrich__"
register_sw = true
```

## Structure

| Path | What |
|------|------|
| `observe/router.py` | Global event router — register sinks, push errors/feedback |
| `observe/sink/sink.py` | `ErrorEvent`, `FeedbackEvent` dataclasses + `Sink` protocol |
| `observe/config/config.py` | `ObserveConfig` dataclass + `toml` loader |
| `observe/receiver/otlp.py` | OTLP span/log → `ErrorEvent` converter |
| `observe/middleware/wsgi.py` | WSGI middleware — injects shim, captures errors |
| `observe/middleware/asgi.py` | ASGI middleware (FastAPI/Starlette) |
| `observe/middleware/http_server.py` | stdlib `http.server` monkey-patch |
| `observe/middleware/go.go` | Go `net/http` middleware |
| `observe/middleware/worker.js` | Cloudflare Workers middleware |
| `observe/shim/observe.js` | Browser shim — fetches, errors, feedback UI |
| `observe/shim/observe.sw.js` | Service worker — offline queue, OTLP buffering |
| `sinks/sentry/*` | Sentry sink (separate package) |

## Runtime

- No dependencies for core package
- Sinks are optional plugins
- Runs in-process — no daemon, no sidecar process
- All event types: `ErrorEvent`, `FeedbackEvent`
- Profiles: `relay` (forward), `full` (local processing), `buffer` (queued)
