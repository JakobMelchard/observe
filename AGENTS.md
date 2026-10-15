# observe

- `ObserveCore` (`src/observe/core.py`) is the only place for route matching, the config blob, shim caching, script injection, binary-extension skipping and OTLP ingest. Never reimplement any of it in a middleware.
- A middleware only reads the body, calls `core.route()`, `core.refuse()`, `core.reply()` and `core.inject()`, and emits the response. Keep it under 100 lines. Test it in `tests/unit/test_adapters.py`.
- A sink implements `push_error(event)` and `push_feedback(event)` from `observe.sink.sink`. Copy `sinks/github/` for a new one, add `sinks/<name>/src` to `pythonpath` and `mypy_path` in the root `pyproject.toml`, test in `tests/e2e/`.
- Config: add a row to `FIELDS` in `src/observe/config/config.py`, not an `if`.
- The core package has zero runtime dependencies. Sinks may have them.
- `observe.sw.js` must leave no globals so an app worker can `importScripts` it. Keep it inside its IIFE.
- Run `uv run pytest`, `uv run mypy`, `uv run ruff check .` and `uv run ruff format --check .` before pushing. The shim JS and its node tests carry JSDoc types: `npm ci && npm run typecheck` (tsc --checkJs, strict; the service worker has its own `tsconfig.sw.json`). biome lints them via `prek run --all-files`.
