# Agent rules — JakobMelchard org

Applies in every org repo. A repo's own `AGENTS.md` adds to this; it does not override it.

## Conduct

- Think first. State assumptions. Ask when the reading changes the work.
- Disagree flatly. No sycophancy.
- Minimal code. No abstractions or features beyond the request.
- Surgical edits. Touch requested code only.
- Verify before asserting: read the file, run the check.
- Concise output. No filler, no em dashes, no emoji.

## Platform (map: `JakobMelchard/.agents/PLATFORM.md`)

- CI: new pipelines call a reusable workflow from `JakobMelchard/.github`; a hand-rolled one you touch gets migrated in the same change.
- Hooks: vendored from `JakobMelchard/.githooks` via `hooks-install`. Never edit a vendored copy; repo checks go in `.githooks/<hook>.local`.
- Lint/format config: vendored from `JakobMelchard/.config` via `config-sync`. Extend, do not fork.
- Dev environment: a template from `JakobMelchard/.devcontainer`.
- Tooling: `JakobMelchard/bin` (`org-repo`, `hooks-install`, `agents-sync`, `config-sync`, `dev-init`, `ci`).
- Skills here are the org set; a repo copies the ones it uses into its own `.agents/skills/` with `agents-sync`.

## Toolset

| Concern | Use |
|---|---|
| scripting | python, bash (3.2-compatible when it runs on macOS), lua (nvim) |
| frontend | vanilla JS + JSDoc (`tsc --checkJs`), plain CSS, htmx. No frameworks, no bundler. |
| backend / tooling | Go, stdlib `net/http`. No web framework. |
| performance-critical | C / C++ |
| infra | opentofu, helm, kubectl |
| edge | Cloudflare Workers / Pages via wrangler |

## Git

- Commits: `conventional-commits` skill. `type(scope): subject`, imperative, lowercase, ≤72 chars.
- PRs: `pr` skill. Draft first; ready only when checks are green.
- Where a `Makefile` exists it is the entrypoint; read it before inventing commands. Otherwise the repo's own `AGENTS.md`/README names the commands.
