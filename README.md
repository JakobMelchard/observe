# observe

In-process observability for Python web apps: error tracking, user feedback and OTLP telemetry,
injected into the pages of the app it wraps. Zero runtime dependencies; sinks are separate packages.

```python
from observe import router
from observe.config.config import load_config
from observe.middleware.wsgi import ObserveMiddleware
from observe_sentry import SentrySink

router.register(SentrySink())
app = ObserveMiddleware(my_wsgi_app, load_config())
```

`observe.middleware.asgi` and `observe.middleware.http_server` are the other adapters.
`SentrySink` forwards `ErrorEvent`s to Sentry. `GitHubSink` (`from observe_github import GitHubSink`)
files `FeedbackEvent`s as issues against `repo` (or the git `origin` remote of `cwd`), authenticating
via `GITHUB_TOKEN` or `GITHUB_APP_ID` + `GITHUB_APP_PRIVATE_KEY` (requires `observe-github[app]`).
`GitHubSink(enrich=fn)` takes an optional callable returning `{"label", "title", "description"}` or `None`.

To try it locally without Sentry or GitHub credentials:

```python
from http.server import BaseHTTPRequestHandler, HTTPServer
from observe import router
from observe.config.config import ObserveConfig
from observe.middleware.http_server import patch_handler


class StdoutSink:
    push_error = staticmethod(print)
    push_feedback = staticmethod(print)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b'<!doctype html><head></head><body><button onclick="nonexistent()">Error</button></body>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


router.register(StdoutSink())
patch_handler(Handler, ObserveConfig())
HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
```

Open `http://127.0.0.1:8000`, submit the Feedback widget or click Error, and `FeedbackEvent` / `ErrorEvent` prints in the terminal.

## Install

<!-- x-release-please-start-version -->
```toml
[tool.uv.sources]
observe = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.5" }
observe-github = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.5", subdirectory = "sinks/github" }
observe-sentry = { git = "https://github.com/JakobMelchard/observe.git", tag = "v0.2.5", subdirectory = "sinks/sentry" }
```
<!-- x-release-please-end -->

`observe`, `observe-github` and `observe-sentry` share one version.

## Commands

```sh
uv sync
uv run pytest
uv run mypy
uv run ruff check . && uv run ruff format --check .
npm ci && npm run typecheck
```

## Config

`load_config()` reads `observe.toml` or `pyproject.toml` in the working directory (or the path it is given); see `observe.toml.example`. A value of the wrong type raises `ValueError` at startup. `ObserveConfig()` alone is the defaults and reads no file. In `pyproject.toml` the tables live under `tool.observe`, e.g. `[tool.observe.collector]`.

| Key                             | Default              | What                                                                                                                               |
| ------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `collector.endpoint`            | `/__observe__/otlp`  | where the browser sends spans; the built-in receiver only listens on the default, so change it only to point at a remote collector |
| `collector.max_body_bytes`      | `1048576`            | larger POSTs get 413                                                                                                               |
| `collector.same_site`           | `true`               | cross-site POSTs get 403, and so does feedback without `Origin` or `Sec-Fetch-Site`                                                |
| `collector.feedback_per_minute` | `10`                 | per client address, 429 beyond; `0` lifts it                                                                                       |
| `collector.feedback_per_day`    | `50`                 | all clients together, 429 beyond; `0` lifts it                                                                                     |
| `collector.otlp_per_minute`     | `300`                | per client address, 429 beyond; `0` lifts it                                                                                       |
| `frontend.feedback_label`       | `Feedback`           | trigger text                                                                                                                       |
| `frontend.enrich_hook`          | `__observe_enrich__` | window function that adds context                                                                                                  |
| `frontend.register_sw`          | `false`              | register `observe.sw.js` as the page's worker                                                                                      |
| `frontend.button`               | `true`               | floating trigger; `false` and call `window.__observe__.open()`                                                                     |

## Frontend

The middleware injects one external tag, `<script src="/__observe__/observe.js" data-config="...">`, and no inline script, so a CSP of `script-src 'self'` is enough.

Without middleware, set `window.__OBSERVE_CONFIG__` before loading `observe.js`: `feedbackEndpoint` and `token` for a remote receiver, `repo` for the issue target, `traces: false` to skip OTLP spans, `registerSw: true` to register the worker, `button: false` to drop the trigger.

To share a page worker with the app, leave `register_sw` off and import it there:

```js
importScripts("/__observe__/observe.sw.js");
```

## Endpoints

| Path                         | Method | What                                                             |
| ---------------------------- | ------ | ---------------------------------------------------------------- |
| `/__observe__/observe.js`    | GET    | browser shim                                                     |
| `/__observe__/observe.sw.js` | GET    | service worker                                                   |
| `/__observe__/config`        | GET    | frontend config JSON                                             |
| `/__observe__/feedback`      | POST   | `FeedbackEvent` to the router; 400 without a non-blank `message` |
| `/__observe__/otlp/...`      | POST   | OTLP JSON to `ErrorEvent`s to the router                         |

## Layout

| Path                             | What                                                                     |
| -------------------------------- | ------------------------------------------------------------------------ |
| `src/observe/core.py`            | routing, injection, OTLP ingest; the adapters only read and write bodies |
| `src/observe/router.py`          | register sinks, fan out events                                           |
| `src/observe/middleware/`        | WSGI, ASGI, `http.server` adapters                                       |
| `src/observe/shim/`              | `observe.js`, `observe.sw.js`                                            |
| `sinks/github/`, `sinks/sentry/` | sink packages                                                            |
