"""Git helpers for describing the code a piece of feedback came from.

Self-contained: shells out to ``git`` in a working directory and degrades to
empty strings whenever that fails.  No repository is assumed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

TIMEOUT = 5


def _git(args: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def gh_repo(cwd: Path | None = None) -> str:
    """Return the ``owner/name`` slug of the origin remote, or an empty string."""
    remote = _git(["remote", "get-url", "origin"], cwd)
    if not remote:
        return ""
    for prefix in ("git@", "https://"):
        if prefix in remote:
            remote = remote.split(prefix, 1)[-1]
    parts = remote.replace(":", "/").removesuffix(".git").split("/")
    return f"{parts[-2]}/{parts[-1]}" if len(parts) >= 2 else ""


def git_context(cwd: Path | None = None, commits: int = 10, diff_range: int = 5) -> str:
    """Summarize branch, recent commits, and recently changed files."""
    sections = [
        ("Branch: {}", _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)),
        (f"\nRecent commits ({commits}):\n{{}}", _git(["log", "--oneline", f"-{commits}"], cwd)),
        (
            f"\nFiles changed (last {diff_range} commits):\n{{}}",
            _git(["diff", "--stat", f"HEAD~{diff_range}", "HEAD"], cwd),
        ),
    ]
    return "\n".join(template.format(value) for template, value in sections if value)
