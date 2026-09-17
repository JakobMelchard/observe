# contrib — unmaintained ports

Ports of the observe middleware to other runtimes.  They predate
`observe/core.py` and do not track it: each reimplements routing, injection
and OTLP parsing on its own, and neither is linted, type-checked, tested, or
packaged.

| File | Runtime | State |
|------|---------|-------|
| `go.go` | Go `net/http` | OTLP parsing incomplete |
| `worker.js` | Cloudflare Workers | untested |

Nothing in this workspace imports either one.  Before using one, port it
against the contract in `observe/core.py` and give it tests.
