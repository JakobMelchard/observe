"""GitHub issue creation as an observe sink.

``push_feedback`` turns a :class:`~observe.sink.sink.FeedbackEvent` into a
GitHub issue.  An optional ``enrich`` callable may supply a title, a leading
description, and a label — the sink never knows what produced them, so an
LLM, a heuristic, or nothing at all can be swapped in at registration time.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from observe.sink.sink import ErrorEvent, FeedbackEvent
from observe_github.gitctx import gh_repo, git_context

log = logging.getLogger(__name__)

EnrichFn = Callable[[FeedbackEvent], dict[str, Any] | None]

API = "https://api.github.com/repos/{repo}/issues"
LOG_TAIL = 50
TIMEOUT = 30


def format_logs(entries: list[Any]) -> str:
    """Render client log entries, accepting both plain strings and log dicts."""
    lines: list[str] = []
    for entry in entries[-LOG_TAIL:]:
        if not isinstance(entry, dict):
            lines.append(f"  {entry}")
            continue
        ts = entry.get("t", 0)
        stamp = datetime.fromtimestamp(ts / 1000, UTC).strftime("%H:%M:%S") if ts else "?"
        detail = f" — {entry['detail']}" if entry.get("detail") else ""
        lines.append(f"  {stamp} [{entry.get('app', '?')}] {entry.get('action', '?')}{detail}")
    return "\n".join(lines)


class GitHubSink:
    """Observe sink that opens a GitHub issue per feedback event.

    Args:
        token: GitHub token.  Defaults to ``GITHUB_TOKEN``.
        repo: ``owner/name`` slug.  Defaults to the origin remote of ``cwd``.
        enrich: Optional callable returning ``label``, ``title``, ``description``.
        cwd: Repository used for the remote slug and code context.
    """

    def __init__(
        self,
        token: str | None = None,
        repo: str | None = None,
        enrich: EnrichFn | None = None,
        cwd: Path | None = None,
    ) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._repo = repo or gh_repo(cwd)
        self._enrich = enrich
        self._cwd = cwd

    def push_error(self, event: ErrorEvent) -> None:
        """Errors do not open issues — only feedback does."""

    def push_feedback(self, event: FeedbackEvent) -> None:
        if not self._token:
            log.warning("GitHubSink: GITHUB_TOKEN not set, skipping")
            return
        if not self._repo:
            log.warning("GitHubSink: could not determine repo, skipping")
            return

        enrichment = self._enriched(event)
        title = (enrichment.get("title") if enrichment else None) or self._title(event)
        url = self._create_issue(
            title, self._body(event, enrichment), enrichment.get("label") if enrichment else None
        )
        if url:
            log.info("GitHubSink: created issue %s", url)

    def _enriched(self, event: FeedbackEvent) -> dict[str, Any] | None:
        if not self._enrich:
            return None
        try:
            return self._enrich(event)
        except Exception:
            log.exception("GitHubSink: enrich callable failed")
            return None

    @staticmethod
    def _title(event: FeedbackEvent) -> str:
        category = _category(event)
        return f"[{category}] {event.message[:120]}"

    def _body(self, event: FeedbackEvent, enrichment: dict[str, Any] | None) -> str:
        parts: list[str] = []
        if enrichment and enrichment.get("description"):
            parts += [enrichment["description"], "", "---", ""]

        user = _as_dict(event.user)
        parts += [
            f"**Message:** {event.message}",
            f"**Category:** {_category(event)}",
            f"**Timestamp:** {event.timestamp or datetime.now(UTC).isoformat()}",
        ]
        parts += [f"**{k.capitalize()}:** {v}" for k, v in user.items() if k != "category" and v]

        context = _as_dict(event.context)
        if context:
            parts.append("\n**Context:**")
            for key, value in context.items():
                if key == "logs" and isinstance(value, list):
                    shown = len(value[-LOG_TAIL:])
                    parts.append(f"\n**Logs (last {shown}):**\n```\n{format_logs(value)}\n```")
                elif value:
                    parts.append(f"- {key}: {value}")

        code = git_context(self._cwd)
        if code:
            parts.append(f"\n\n**Code context:**\n{code}")
        return "\n".join(parts)

    def _create_issue(self, title: str, body: str, label: str | None) -> str | None:
        payload: dict[str, Any] = {"title": title, "body": body}
        if label:
            payload["labels"] = [label]
        request = urllib.request.Request(
            API.format(repo=self._repo),
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "observe-github-sink/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
                result: str | None = json.loads(resp.read()).get("html_url")
                return result
        except urllib.error.HTTPError as exc:
            log.error("GitHubSink: HTTP %d creating issue: %s", exc.code, exc.read().decode())
        except Exception as exc:
            log.error("GitHubSink: failed to create issue: %s", exc)
        return None


def _category(event: FeedbackEvent) -> str:
    return _as_dict(event.user).get("category") or "feedback"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
