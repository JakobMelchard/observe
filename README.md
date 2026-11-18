# observe

## Purpose

- Demonstrates dependency-free Python middleware, browser instrumentation and pluggable telemetry sinks.
- Injects error tracking, feedback and OTLP JSON collection into WSGI, ASGI or `http.server` apps.

## Usage

Run a local WSGI demo without sink credentials:

```sh
git clone https://github.com/JakobMelchard/observe.git
cd observe
uv sync
uv run python - <<'PY'
from wsgiref.simple_server import make_server
from observe.config.config import ObserveConfig
from observe.middleware.wsgi import ObserveMiddleware
def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/html")])
    return [b"<!doctype html><html><head></head><body>Observe demo</body></html>"]
make_server("127.0.0.1", 8000, ObserveMiddleware(app, ObserveConfig())).serve_forever()
PY
```

- Open `http://127.0.0.1:8000`; feedback is accepted but not persisted until a sink is registered.
- Register with `from observe import router; router.register(sink)`: `observe_github.GitHubSink` files feedback as issues; `observe_sentry.SentrySink` forwards errors.
- GitHub: `repo` or `cwd`'s git origin; `GITHUB_TOKEN` or `GITHUB_APP_ID` + `GITHUB_APP_PRIVATE_KEY` with `observe-github[app]`; optional `enrich` callable.
- `load_config()` reads `observe.toml` or `pyproject.toml` (`tool.observe`); invalid types raise `ValueError`. `ObserveConfig()` reads no files. See [fields](observe.toml.example).
- Middleware serves `/__observe__/observe.js`, `observe.sw.js`, `config`, `feedback` and `otlp/...`.
- External injection supports `script-src 'self'`; worker registration is opt-in. Share an app worker with `importScripts("/__observe__/observe.sw.js")`.
- Standalone shim config: `window.__OBSERVE_CONFIG__`; feedback UI: `window.__observe__.open()`.

Pin packages in a consuming project's `pyproject.toml`:

<!-- x-release-please-start-version -->
```toml
[tool.uv.sources]
observe = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.6" }
observe-github = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.6", subdirectory = "sinks/github" }
observe-sentry = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.6", subdirectory = "sinks/sentry" }
```
<!-- x-release-please-end -->

## Layout

```text
src/observe/              # core routing/injection/OTLP, sink router, typed config
src/observe/middleware/   # WSGI, ASGI and http.server adapters
src/observe/shim/         # browser script and service worker
sinks/                    # separately packaged GitHub and Sentry adapters
tests/                    # Python unit/integration and Node shim tests
.github/workflows/        # shared Python, Node, hooks and release CI
```

## Operate

- Owner: JakobMelchard. Library only; deployment belongs to the consuming app.
- Deploy: install the pinned packages, register sinks and wrap the application's handler.
- Rollback: restore the previous dependency pins and redeploy the consuming app; no hosted rollback command.
- CI: Python tests/lint/types, shim type checks and prek hooks on PRs and main; release-please owns versions.
- Core and sink packages share one version. No package-upload job is defined here.

```sh
uv run pytest
uv run mypy
uv run ruff check . && uv run ruff format --check .
npm ci && npm run typecheck
prek run --all-files
```

## Dependencies

- Runtime: Python 3.11+, no core dependencies; optional sinks have separate requirements and need GitHub/Sentry only when configured.
- Development: uv, Node.js/npm (supported versions in `package.json`), prek; locked Python and Node tooling.

## Status

- Live: versioned library and adapters with automated tests; downstream deployment unverified. Planned: retain as a minimal observability showcase, no new service.
