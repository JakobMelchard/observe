# observe

Deployment-agnostic observability for Python web apps, with no core dependencies. Adds
error tracking, a feedback widget and OTLP JSON collection to WSGI, ASGI and
`http.server` apps, and forwards events to pluggable sinks.

```text
request ──▶ middleware (WSGI / ASGI / http.server)
                │
                ▼
            core router ──▶ shim, config, feedback, OTLP ingest
                │
                ▼
            sink router ──▶ GitHub issues
                        └─▶ Sentry
```

## Install

```sh
pip install observe-github observe-sentry   # or install from git, see below
```

Source overrides for a consuming project's `pyproject.toml`; also declare the desired
packages in `project.dependencies`:

<!-- x-release-please-start-version -->
```toml
[tool.uv.sources]
observe = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.6" }
observe-github = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.6", subdirectory = "sinks/github" }
observe-sentry = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.6", subdirectory = "sinks/sentry" }
```
<!-- x-release-please-end -->

## Quickstart

```sh
uv sync
uv run python examples/wsgi_demo.py
```

Open <http://127.0.0.1:8000>. Feedback is accepted but not persisted until a sink is
registered.

```python
from observe import router

router.register(sink)  # observe_github.GitHubSink or observe_sentry.SentrySink
```

## Configure

- `load_config()` reads `observe.toml` or `pyproject.toml` (`tool.observe`); invalid types raise `ValueError`. `ObserveConfig()` reads no files. See [fields](observe.toml.example).
- GitHub sink: `repo` or the `cwd` git origin; `GITHUB_TOKEN`, or `GITHUB_APP_ID` plus `GITHUB_APP_PRIVATE_KEY` with `observe-github[app]`; optional `enrich` callable.
- Middleware serves `/__observe__/observe.js`, `observe.sw.js`, `config`, `feedback` and `otlp/...`.
- External injection supports `script-src 'self'`; worker registration is opt-in. Share an app worker with `importScripts("/__observe__/observe.sw.js")`.
- Standalone shim: set `window.__OBSERVE_CONFIG__` before loading `observe.js`. Feedback UI: `window.__observe__.open()`.

## Layout

```text
src/observe/              core routing, injection, OTLP and typed config
src/observe/middleware/   WSGI, ASGI and http.server adapters
src/observe/shim/         browser script and service worker
sinks/                    separately packaged GitHub and Sentry adapters
examples/                 minimal WSGI demo
tests/                    Python unit/integration and Node shim tests
```

## Development

```sh
uv run pytest
uv run mypy
uv run ruff check . && uv run ruff format --check .
npm ci && npm run typecheck
prek run --all-files
```

Runtime: Python 3.11+, no core dependencies. Sinks have their own requirements and need
GitHub or Sentry only when configured.

## License

MIT, see [LICENSE](LICENSE).
