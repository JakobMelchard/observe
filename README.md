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

Feedback straight to GitHub issues:

```python
from observe_github import GitHubSink

router.register(GitHubSink(enrich=my_enricher))
```

`enrich` is any `FeedbackEvent -> {"label", "title", "description"} | None`. The
sink never knows what produced it — an LLM, a heuristic, or nothing at all.

It authenticates as a **GitHub App** when one is configured, which is what a
service opening issues on its own should use: scoped to the repositories the
App is installed on, tied to no one's account, revocable on its own.

```sh
pip install 'observe-github[app]'     # RSA signing; the base install has no deps
export GITHUB_APP_ID=123456
export GITHUB_APP_PRIVATE_KEY="$(cat app.private-key.pem)"
```

The PEM survives being flattened to `\n` escapes or base64-wrapped, which is
what secret stores tend to do to it. Installation tokens are minted on demand
and reused until shortly before they expire. `GITHUB_TOKEN` still works and
takes precedence if set.

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

## Design

In-process. No daemon, no separate process, no infrastructure dependency.

```
Browser/Client                 App Server                    Sinks
┌───────────┐    errors    ┌──────────────────┐   events   ┌──────────┐
│ observe.js│─────────────→│ middleware       │───────────→│ Sentry   │
│  (shim)   │   feedback   │  (thin adapter)  │            ├──────────┤
│           │─────────────→│      ↓           │───────────→│ GitHub   │
│           │     OTLP     │  ObserveCore     │            ├──────────┤
│ observe.  │─────────────→│      ↓           │───────────→│ your own │
│   sw.js   │              │  router          │            └──────────┘
└───────────┘              └──────────────────┘
```

`src/observe/core.py` owns everything that does not depend on the transport:
which paths belong to observe, what each replies, which responses get the shim
injected, and how OTLP payloads reach the router. Each middleware is a thin
adapter over it that only reads bodies and emits responses.

**Profiles:** `relay` (forward immediately), `buffer` (queue in memory, flush on
condition), `full` (local processing + forwarding).

## Structure

| Path | What |
|------|------|
| `src/observe/core.py` | Transport-agnostic routing, injection, OTLP ingest |
| `src/observe/router.py` | Global event router — register sinks, push errors/feedback |
| `src/observe/sink/sink.py` | `ErrorEvent`, `FeedbackEvent` dataclasses + `Sink` protocol |
| `src/observe/config/config.py` | `ObserveConfig` dataclass + `toml` loader |
| `src/observe/receiver/otlp.py` | OTLP span/log → `ErrorEvent` converter |
| `src/observe/middleware/wsgi.py` | WSGI adapter |
| `src/observe/middleware/asgi.py` | ASGI adapter (FastAPI/Starlette) |
| `src/observe/middleware/http_server.py` | stdlib `http.server` handler patch |
| `src/observe/shim/observe.js` | Browser shim — fetches, errors, feedback UI |
| `src/observe/shim/observe.sw.js` | Service worker — offline queue, OTLP buffering |
| `sinks/sentry/` | Sentry sink (separate package) |
| `sinks/github/` | GitHub issue sink (separate package) |
| `contrib/` | Unmaintained Go and Cloudflare Workers ports |

## Endpoints

Every middleware serves the same five paths:

| Path | Method | What |
|------|--------|------|
| `/__observe__/observe.js` | GET | Browser shim |
| `/__observe__/observe.sw.js` | GET | Service worker |
| `/__observe__/config` | GET | Frontend config JSON |
| `/__observe__/feedback` | POST | `FeedbackEvent` → router |
| `/__observe__/otlp/...` | POST | OTLP JSON → `ErrorEvent`s → router |

Everything else is delegated to the wrapped app. 2xx `text/html` responses get
the shim injected after `<head>`; binary extensions are skipped untouched.

## Runtime

- No dependencies for the core package
- Sinks are optional plugins, each its own distributable package
- Runs in-process — no daemon, no sidecar process
