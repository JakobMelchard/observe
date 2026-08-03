## Skill: observe middleware

### Adding middleware for a new framework

1. Create `observe/middleware/<name>.<ext>`
2. Accept `(app, config)` — app is the framework's handler, config is `ObserveConfig`
3. Serve shims at `__observe__/observe.js` and `__observe__/observe.sw.js`
4. Serve config JSON at `__observe__/config`
5. Handle POST to `__observe__/feedback` — parse JSON, call `router.push_feedback()`
6. Handle POST to `__observe__/otlp/...` — parse JSON, call OTLP converters
7. Intercept HTML responses — inject `<script src="/__observe__/observe.js">` before `</head>`
8. Skip injection for binary content types

### WSGI pattern (reference)

```python
class ObserveMiddleware:
    def __init__(self, app, config):
        self.app = app
        self.cfg = config

    def __call__(self, environ, start_response):
        path = environ["PATH_INFO"]
        if path == "/__observe__/observe.js":
            return self._serve_shim("observe.js", start_response)
        # ... handle other endpoints ...
        return self._inject_script(environ, start_response)
```

### Testing

- Use `werkzeug.test.Client` for WSGI
- Register a test sink to verify events reach router
- Verify HTML injection with `b"observe.js" in resp.data`
- Verify binary responses are not injected
