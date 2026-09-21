# observe — Observability sidecar

Python library for instrumenting apps with error tracking and user feedback. Pluggable sinks, multiple deployment profiles.

## Structure

```
observe/
├── src/observe/                # Core package
│   ├── core.py                # ObserveCore — transport-agnostic half
│   ├── router.py              # Global event router
│   ├── config/config.py       # ObserveConfig + TOML loader
│   ├── receiver/otlp.py       # OTLP → ErrorEvent converter
│   ├── middleware/             # Thin adapters over ObserveCore
│   │   ├── wsgi.py            # WSGI
│   │   ├── asgi.py            # ASGI
│   │   └── http_server.py     # stdlib http.server patch
│   ├── shim/
│   │   ├── observe.js         # Browser shim
│   │   └── observe.sw.js      # Service worker buffer
│   └── sink/sink.py           # Event types + Sink protocol
├── sinks/sentry/              # Sentry sink package
├── sinks/github/              # GitHub issue sink package
├── contrib/                   # Unmaintained Go / CF Workers ports
├── tests/
│   ├── unit/test_core.py      # ObserveCore contract
│   ├── unit/test_adapters.py  # ASGI + http.server adapters
│   ├── unit/test_middleware.py# WSGI adapter
│   ├── e2e/test_sentry.py     # Sink event shapes
│   └── fixture/
└── pyproject.toml
```

## Commands

```sh
uv sync --extra dev              # install deps
uv run pytest                    # run tests
uv run mypy                      # type check (strict)
uv run ruff check .              # lint
uv run ruff format .             # format
```

CI runs all four on every PR (`.github/workflows/ci.yml`).

## Key patterns

- **ObserveCore is the single implementation.** Route matching, the config
  blob, shim caching, script-tag injection, binary-extension skipping and OTLP
  ingest live in `observe/core.py` and nowhere else. If you find yourself
  writing any of them in a middleware, you are writing a bug.
- **Middlewares are adapters.** They read a request body the way their
  transport does, call `core.route()` / `core.reply()`, emit a response, and
  call `core.inject()` on 2xx HTML. Nothing else.
- **Sink protocol**: implement `push_error(event)` + `push_feedback(event)`.
- **Router**: singleton — register sinks, broadcasts events to all.
- **Config**: auto-discovers `observe.toml` or `pyproject.toml` in cwd. The
  `FIELDS` table maps `(section, key) → attribute`; add a row, not an `if`.
- **No dependencies**: core package has zero runtime deps. Sinks may have them.

## Adding a middleware

1. Create `observe/middleware/<transport>.py`.
2. Hold an `ObserveCore`. Implement only: read body, emit reply, intercept the
   wrapped app's response, inject. Target under 100 lines.
3. Add adapter tests in `tests/unit/test_adapters.py`.

## Adding a sink

1. Create `sinks/<name>/` with a `pyproject.toml` (copy `sinks/github/`).
2. Implement the `Sink` protocol from `observe.sink.sink`.
3. Add `sinks/<name>/src` to `pythonpath` and `mypy_path` in the root
   `pyproject.toml` so tests and mypy see it.
4. Add tests in `tests/e2e/`.

## Known issues

- No protobuf OTLP support — JSON only. Non-JSON content types are ignored.
- Service worker uses IndexedDB for the offline queue (no Cache API).
- `contrib/` ports are not linted, typed, tested, or packaged.
