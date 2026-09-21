---
name: conventional-commits
description: Use when writing git commit messages or when the user says "commit", "make a commit", or invokes /commit. Enforces Conventional Commits with subject-only messages by default; body only when the change spans multiple sections, in which case the body enumerates them.
version: 1.0.0
---

# Conventional commits

## Format

```
<type>(<scope>): <subject>
```

- **type**: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `style`, `perf`, `build`, `ci`, `revert`.
- **scope**: optional. One word, lowercase, the area touched (`auth`, `parser`, `ghostty`).
- **subject**: imperative, lowercase, no trailing period, ≤ 72 chars.

Default: **subject only, no body**.

## When to add a body

Only when the commit spans **multiple sections** (multiple files/areas/concerns that don't share a single scope). The body is then a bare bullet list enumerating each section.

```
chore: update shell helpers

- zshrc: adjust prompt hooks and project widget
- ghostty: enable shell integration
- bin: chmod +x proj
```

No prose paragraph. No "this commit does X because Y". The bullets *are* the body.

## Never include

- Trailing summaries ("This makes the code cleaner.").
- Issue/PR references unless the user explicitly asked.
- Generated trailers (`Co-Authored-By`, etc.) unless the user explicitly asked or repo convention requires them.
- Emoji, unless the user asked.

## Examples

```
feat(auth): add refresh-token rotation
fix(parser): handle empty input
chore: bump deps
refactor(api): extract pagination helper
docs: clarify gitx layout
```

Multi-section:
```
refactor: split project helpers across tools

- ctx: add native nvim session attach
- proj: share project-root discovery
- zshrc: drop attach wrapper path
```
