# observe architecture

## Design

Observe is an in-process observability sidecar — it runs inside your application process, intercepts requests/responses at the middleware layer, and routes events to configurable sinks.

No daemon, no separate process, no infrastructure dependency.

## Data flow

```
Browser/Client                    App Server                     Sink
┌──────────┐     HTTP     ┌──────────────────┐     push      ┌──────────┐
│ observe.js│──────────→│ Middleware        │────────────→│ Sentry   │
│ (shim)   │  errors    │ (wsgi/asgi/go/js)│  ErrorEvent  │ (plugin) │
│          │  feedback  │                  │  Feedback     └──────────┘
│          │──────────→│                  │────────────→┌──────────┐
│          │  OTLP     │  Router          │  Event       │ stdout  │
└──────────┘           │  (singleton)     │────────────→└──────────┘
                       └──────────────────┘
```

## Profiles

- **relay**: forward events to configured sinks immediately
- **buffer**: queue events in memory, flush on condition
- **full**: local processing + forwarding

## Middleware

Each middleware:
1. Serves static JS shims at `__observe__/observe.js` and `__observe__/observe.sw.js`
2. Serves config JSON at `__observe__/config`
3. Handles OTLP ingest at `__observe__/otlp/...`
4. Handles feedback at `__observe__/feedback`
5. Injects shim script tag into HTML responses
6. Skips binary content types (images, fonts, etc.)

## Sinks

Sinks implement `Sink` protocol — `push_error(ErrorEvent)` and `push_feedback(FeedbackEvent)`. Multiple sinks can be registered; all receive all events.

## Browser shim

The client-side JS (`observe.js`):
- Wraps `fetch()` to capture non-2xx responses and network errors
- Captures `window.onerror` and `unhandledrejection`
- Submits user feedback via `__observe__/feedback` endpoint
- Registers service worker for offline OTLP buffering

## Service worker

`observe.sw.js`:
- Intercepts OTLP POST requests
- On network failure: queues in IndexedDB
- On `sync` event or coming online: flushes queued events
- Max queue: 500 events
