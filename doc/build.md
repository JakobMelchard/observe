# observe — build & CI/CD

## Build

Core package is pure Python — no build step. Published as source distribution.

```sh
uv build
```

## Test

```sh
uv run pytest -v              # unit + e2e tests
uv run pytest tests/unit/     # middleware tests only
uv run pytest tests/e2e/      # sink integration tests
```

## Lint & format

```sh
uv run ruff check .           # lint
uv run ruff format --check .  # format check
uv run ruff format .          # auto-format
```

## Dependencies

- Core: zero runtime dependencies
- Dev: `pytest`, `ruff`, `werkzeug` (test client)
- Sentry sink: `sentry-sdk>=2`

## Sink packages

Each sink in `sinks/` is a separate distributable package:
- `observe-sentry` — Sentry sink

Sinks depend on `observe` as a git dependency:

```toml
dependencies = ["observe @ git+https://github.com/JakobMelchard/observe.git"]
```

## CI (planned)

- PR: `ruff check` + `pytest`
- Push to main: publish to PyPI
- Per-sink: separate CI jobs
