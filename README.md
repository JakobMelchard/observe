# observe

In-process observability for Python web apps: error tracking, user feedback and OTLP telemetry,
injected into the pages of the app it wraps. Zero runtime dependencies; sinks are separate packages.

```python
from observe import router
from observe.config.config import ObserveConfig
from observe.middleware.wsgi import ObserveMiddleware
from observe_sentry import SentrySink

router.register(SentrySink())
app = ObserveMiddleware(my_wsgi_app, ObserveConfig())
```

`observe.middleware.asgi` and `observe.middleware.http_server` are the other adapters.
`GitHubSink(enrich=fn)` files feedback as issues; `fn` takes a `FeedbackEvent` and returns
`{"label", "title", "description"}` or `None`.

## Install

```toml
[tool.uv.sources]
observe = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.2" }
observe-github = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.2", subdirectory = "sinks/github" }
observe-sentry = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.2", subdirectory = "sinks/sentry" }
```

`observe`, `observe-github` and `observe-sentry` share one version.

## Commands

```sh
uv sync
uv run pytest
uv run mypy
uv run ruff check . && uv run ruff format --check .
```

## Config

`observe.toml` or `pyproject.toml` in the working directory; see `observe.toml.example`. In `pyproject.toml` the tables live under `tool.observe`, e.g. `[tool.observe.collector]`.

| Key | Default | What |
|-----|---------|------|
| `collector.endpoint` | `/__observe__/otlp` | where the browser sends spans; the built-in receiver only listens on the default, so change it only to point at a remote collector |
| `collector.max_body_bytes` | `1048576` | larger POSTs get 413 |
| `collector.same_site` | `true` | cross-site POSTs get 403, and so does feedback without `Origin` or `Sec-Fetch-Site` |
| `collector.feedback_per_minute` | `10` | per client address, 429 beyond; `0` lifts it |
| `collector.feedback_per_day` | `50` | all clients together, 429 beyond; `0` lifts it |
| `collector.otlp_per_minute` | `300` | same |
| `frontend.feedback_label` | `Feedback` | trigger text |
| `frontend.enrich_hook` | `__observe_enrich__` | window function that adds context |
| `frontend.register_sw` | `false` | register `observe.sw.js` as the page's worker |
| `frontend.button` | `true` | floating trigger; `false` and call `window.__observe__.open()` |

## Frontend

Without middleware, set `window.__OBSERVE_CONFIG__` before loading `observe.js`: `feedbackEndpoint` and `token` for a remote receiver, `repo` for the issue target, `traces: false` to skip OTLP spans, `registerSw: true` to register the worker, `button: false` to drop the trigger.

To share a page worker with the app, leave `register_sw` off and import it there:

```js
importScripts("/__observe__/observe.sw.js");
```

## Endpoints

| Path | Method | What |
|------|--------|------|
| `/__observe__/observe.js` | GET | browser shim |
| `/__observe__/observe.sw.js` | GET | service worker |
| `/__observe__/config` | GET | frontend config JSON |
| `/__observe__/feedback` | POST | `FeedbackEvent` to the router |
| `/__observe__/otlp/...` | POST | OTLP JSON to `ErrorEvent`s to the router |

## Layout

| Path | What |
|------|------|
| `src/observe/core.py` | routing, injection, OTLP ingest; the adapters only read and write bodies |
| `src/observe/router.py` | register sinks, fan out events |
| `src/observe/middleware/` | WSGI, ASGI, `http.server` adapters |
| `src/observe/shim/` | `observe.js`, `observe.sw.js` |
| `sinks/github/`, `sinks/sentry/` | sink packages |
