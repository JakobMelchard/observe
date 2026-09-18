---
name: pr
description: Use when creating a pull request, running CI checks, or iterating on a PR until checks pass. Uses sem for entity-level diffs and blast radius in PR bodies. Triggers on "open pr", "create pr", "pr loop", "fix checks", or /pr.
version: 3.0.0
---

# PR

Create a pull request, then iterate autonomously until all required checks pass.

Composes: **conventional-commits** skill for all commit messages.

Requires: `sem` on PATH (https://github.com/Ataraxy-Labs/sem). If unavailable, fall back to manual file listing in the PR body.

## Create

**always create as draft**.

Title is `<INDICATOR>: <SUMMARY>` where `<INDICATOR>` is specified by
- `<ISSUE-NUMBER>` if working on a dedicated jira / linear task or
- conventional commit type otherwise

### 1. Gather entity-level changes

```sh
sem diff --from <base-sha> --to <head-sha> --format markdown
```

Also run without `--format markdown` to get the box output for the PR body:

```sh
sem diff --from <base-sha> --to <head-sha>
```

For each entity in the markdown output, note:
- file, type, name, status for the Changes section

### 2. Gather blast radius

For each entity with structural changes:

```sh
sem impact <entityId> --json
```

Collect direct dependents and affected tests. Skip entities with no dependents.

### 3. Build PR body

```
<one sentence. what does this PR do?>

<optional: one more sentence if the change is fragmented across concerns>

## Changes

### <filename>

```
┌─ <filename> ────────────────────────────────────────
│
│  <sem diff output for this file>
│
└───────────────────────────────────────────────────────
```

- <bullet: what changed in this file, include sem impact for relevant objects>

### <filename>

```
┌─ <filename> ────────────────────────────────────────
│
│  <sem diff output for this file>
│
└───────────────────────────────────────────────────────
```

- <bullet: what changed in this file, include sem impact for relevant objects>

## Tasks

- [ ] <manual intervention task>
```

Structure:
- First line: single sentence summarizing the full change
- Second paragraph (optional): only if the change spans unrelated concerns, enumerate them
- `## Changes`: one `### <filename>` section per changed file
- Under each filename: sem diff box (verbatim from `sem diff`), then concise bullet list of what changed, include sem impact for relevant objects
- `## Tasks`: only if there are manual intervention tasks, omit section entirely if none
- Omit files with only cosmetic/whitespace changes

**style**: lowercase, terse, technical. no fluff. no em dash.

**body and comments** reference only changes relative to the target branch. Never reference ephemeral session work.

### template location

use `.agents/templates/pr-template.md` or `.github/pull_request_template.md` if exists in repo. sem output replaces the `## Changes` and `## Blast Radius` sections; other sections come from the template.

### 4. Create PR

```sh
gh pr create \
  --draft \
  --title "<title>" \
  --body "<body from step 3>"
```

### Before creating

Check whether a PR already exists for the current branch:

```sh
gh pr view --json url,state 2>/dev/null
```

If open: skip creation, proceed to the checks loop.
If closed/merged: warn the user before proceeding.

## Checks loop

Run after creation and after every push. Repeat until all required checks have `bucket == "pass"`.

### 1. Fetch check status

```sh
gh pr checks --json name,state,bucket,link
```

`bucket` values: `pass`, `fail`, `pending`, `skipping`, `cancel`.

Treat `cancel` as `pending` on first occurrence (transient), as `fail` on recurrence.

### 2. Read PR comments

Fetch comments each iteration to catch reviewer feedback before fixing:

```sh
gh pr view --json comments --jq '.comments[] | {author: .author.login, body: .body, createdAt: .createdAt}'
```

Address explicit reviewer requests in the same fix pass when possible.

### 3. Fix failures

For each check with `bucket == "fail"`:

```sh
# extract run ID from the link field (last path segment)
gh run view <run-id> --log-failed
```

Read the log, identify root cause, make the minimal fix.

For linting / formatting failures, prefer the repo's own tooling:

```sh
# examples, use whatever the repo provides
npm run lint --fix
npx prettier --write .
cargo fmt
ruff check --fix .
```

### 4. Commit and push

Apply the **conventional-commits** skill. Keep the fix commit minimal and scoped to what broke.

```sh
git add -A
git commit -m "fix(scope): address <check-name> failure"
```

Summarize the fix using sem before pushing:

```sh
sem diff --format json   # entity-level summary of what the fix changed
```

Post a comment with the entity-level summary:

```sh
gh pr comment --body "Fixed <check-name>: <entityType> \`<entityName>\` in <file>"
```

Then push:

```sh
git push
```

### 5. Wait for checks to refresh

```sh
# poll with timeout; exit code 8 means pending
timeout 300s gh pr checks --watch --interval 15 \
  || true   # don't abort on pending/timeout
```

Then re-fetch status from step 1.

### 6. Loop exit conditions

| Condition | Action |
|---|---|
| All required buckets `pass` | Done, loop exits |
| Same check fails 3+ consecutive iterations without code change | Surface blocker to user, stop loop |
| Unrecognised failure (no log, no run ID) | Surface to user |
| User explicitly says to stop | Stop immediately |

### 7. Update PR description

Rebuild the body from sem to reflect accumulated fixes. Run the same steps as Create (sem diff + sem impact) and replace the body:

```sh
gh pr edit --body "<rebuilt body from sem diff + sem impact>"
```

## After the loop

Once all checks pass:

1. Mark the PR ready for review: `gh pr ready`

**note**: pr must start as draft (`--draft` flag), only mark ready when checks pass and content is final.
