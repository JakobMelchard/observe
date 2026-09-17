"""Verify GitHubSink turns FeedbackEvents into the issue payload we expect.

Does NOT call the GitHub API — ``_create_issue`` is captured, so these assert
title/body/label composition and the enrich contract only.
"""

import pytest
from observe_github import GitHubSink, format_logs

from observe.sink.sink import ErrorEvent, FeedbackEvent


@pytest.fixture
def capture(monkeypatch):
    calls = []

    def fake(self, title, body, label):
        calls.append({"title": title, "body": body, "label": label})
        return "https://github.test/issues/1"

    monkeypatch.setattr(GitHubSink, "_create_issue", fake)
    monkeypatch.setattr("observe_github.sink.git_context", lambda cwd=None: "")
    return calls


def sink(**kwargs):
    return GitHubSink(token="t", repo="o/r", **kwargs)


def event(**kwargs):
    base = {"message": "button does nothing", "timestamp": "2025-01-01T00:00:00Z"}
    return FeedbackEvent(**{**base, **kwargs})


class TestIssueComposition:
    def test_title_falls_back_to_category_and_message(self, capture):
        sink().push_feedback(event(user={"category": "bug"}))
        assert capture[0]["title"] == "[bug] button does nothing"

    def test_category_defaults_to_feedback(self, capture):
        sink().push_feedback(event())
        assert capture[0]["title"].startswith("[feedback]")

    def test_title_is_truncated(self, capture):
        sink().push_feedback(event(message="x" * 500))
        assert capture[0]["title"] == "[feedback] " + "x" * 120

    def test_body_carries_message_and_timestamp(self, capture):
        sink().push_feedback(event())
        body = capture[0]["body"]
        assert "**Message:** button does nothing" in body
        assert "**Timestamp:** 2025-01-01T00:00:00Z" in body

    def test_body_lists_user_fields_except_category(self, capture):
        sink().push_feedback(event(user={"category": "bug", "name": "jakob"}))
        body = capture[0]["body"]
        assert "**Name:** jakob" in body
        assert "**Category:** bug" in body

    def test_body_lists_context(self, capture):
        sink().push_feedback(event(context={"app": "editor"}))
        assert "- app: editor" in capture[0]["body"]

    def test_body_renders_logs_as_code_block(self, capture):
        logs = [{"t": 0, "app": "editor", "action": "save", "detail": "stem-1"}]
        sink().push_feedback(event(context={"logs": logs}))
        body = capture[0]["body"]
        assert "**Logs (last 1):**" in body
        assert "[editor] save — stem-1" in body

    def test_no_label_without_enrichment(self, capture):
        sink().push_feedback(event())
        assert capture[0]["label"] is None


class TestEnrichContract:
    def test_enrichment_overrides_title_and_adds_label(self, capture):
        sink(enrich=lambda e: {"label": "jules", "title": "Save button inert"}).push_feedback(
            event()
        )
        assert capture[0]["title"] == "Save button inert"
        assert capture[0]["label"] == "jules"

    def test_description_is_prepended_above_a_rule(self, capture):
        sink(enrich=lambda e: {"description": "summary"}).push_feedback(event())
        body = capture[0]["body"]
        assert body.startswith("summary\n\n---\n")
        assert body.index("---") < body.index("**Message:**")

    def test_enrich_returning_none_falls_back(self, capture):
        sink(enrich=lambda e: None).push_feedback(event())
        assert capture[0]["title"] == "[feedback] button does nothing"

    def test_failing_enrich_still_creates_the_issue(self, capture):
        def boom(_):
            raise RuntimeError("ollama down")

        sink(enrich=boom).push_feedback(event())
        assert capture[0]["title"] == "[feedback] button does nothing"

    def test_enrich_receives_the_event(self, capture):
        seen = []
        sink(enrich=seen.append).push_feedback(event())
        assert seen[0].message == "button does nothing"


class TestNoOp:
    def test_missing_token_skips(self, capture):
        GitHubSink(token="", repo="o/r").push_feedback(event())
        assert capture == []

    def test_undiscoverable_repo_skips(self, capture, monkeypatch):
        monkeypatch.setattr("observe_github.sink.gh_repo", lambda cwd=None: "")
        GitHubSink(token="t").push_feedback(event())
        assert capture == []

    def test_errors_do_not_create_issues(self, capture):
        sink().push_error(ErrorEvent(message="boom", level="error", timestamp=""))
        assert capture == []


class TestFormatLogs:
    def test_plain_strings_pass_through(self):
        assert format_logs(["a", "b"]) == "  a\n  b"

    def test_dicts_are_rendered(self):
        out = format_logs([{"t": 0, "app": "editor", "action": "save"}])
        assert out == "  ? [editor] save"

    def test_tail_is_capped_at_50(self):
        assert len(format_logs([f"l{i}" for i in range(80)]).splitlines()) == 50

    def test_missing_fields_become_question_marks(self):
        assert format_logs([{}]) == "  ? [?] ?"
