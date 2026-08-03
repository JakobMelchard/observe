# observe — Observability sidecar

Python library for instrumenting apps with error tracking and user feedback. Pluggable sinks, multiple deployment profiles.

## Structure

```
observe/
├── observe/                    # Core package
│   ├── router.py              # Global event router
│   ├── config/config.py       # ObserveConfig + TOML loader
│   ├── receiver/otlp.py       # OTLP → ErrorEvent converter
│   ├── middleware/             # Per-framework middleware
│   │   ├── wsgi.py            # WSGI middleware
│   │   ├── asgi.py            # ASGI middleware
│   │   ├── http_server.py     # stdlib http.server patch
│   │   ├── go.go              # Go net/http middleware
│   │   └── worker.js          # CF Workers middleware
│   ├── shim/
│   │   ├── observe.js         # Browser shim
│   │   └── observe.sw.js      # Service worker buffer
│   └── sink/sink.py           # Event types + Sink protocol
├── sinks/sentry/              # Sentry sink package
│   └── src/observe_sentry/
├── tests/
│   ├── unit/test_middleware.py
│   ├── e2e/test_sentry.py
│   └── fixture/
└── pyproject.toml
```

## Commands

```sh
uv sync                          # install deps
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format --check .     # format check
```

## Key patterns

- **Sink protocol**: implement `push_error(event)` + `push_feedback(event)`
- **Router**: singleton — register sinks, broadcasts events to all
- **Middleware**: wraps app, injects browser shim into HTML, serves endpoints at `__observe__/`
- **Shim**: client-side JS captures fetch errors, uncaught exceptions, unhandled rejections
- **Config**: auto-discovers `observe.toml` or `pyproject.toml` in cwd
- **No dependencies**: core package has zero runtime deps
- **Optional sinks**: `observe-sentry` depends on `sentry-sdk`

## Adding a middleware

1. Create `observe/middleware/<framework>.py`
2. Follow the WSGI pattern: accept app + config, inject shim into HTML, serve `__observe__/` endpoints
3. Add tests in `tests/unit/`

## Adding a sink

1. Create `sinks/<name>/` with `pyproject.toml`
2. Implement `Sink` protocol from `observe.sink.sink`
3. Add e2e test in `tests/e2e/`

## Known issues

- No protobuf OTLP support yet — JSON only
- Service worker uses IndexedDB for offline queue (no Cache API)
- Go middleware is minimal — OTLP parsing not fully implemented
