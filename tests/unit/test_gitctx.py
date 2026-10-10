"""gh_repo and git_context: parsing a remote slug, summarizing recent history."""

import subprocess
from pathlib import Path

from observe_github.gitctx import gh_repo, git_context


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["init", "-q"], repo)
    _run(["config", "user.email", "a@b.c"], repo)
    _run(["config", "user.name", "a"], repo)
    return repo


class TestGhRepo:
    def test_no_remote_is_empty(self, tmp_path: Path):
        assert gh_repo(_repo(tmp_path)) == ""

    def test_https_remote(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _run(["remote", "add", "origin", "https://github.com/JakobMelchard/observe.git"], repo)
        assert gh_repo(repo) == "JakobMelchard/observe"

    def test_ssh_remote(self, tmp_path: Path):
        repo = _repo(tmp_path)
        _run(["remote", "add", "origin", "git@github.com:JakobMelchard/observe.git"], repo)
        assert gh_repo(repo) == "JakobMelchard/observe"

    def test_not_a_repo_is_empty(self, tmp_path: Path):
        assert gh_repo(tmp_path) == ""


class TestGitContext:
    def test_includes_branch_and_commit(self, tmp_path: Path):
        repo = _repo(tmp_path)
        (repo / "f.txt").write_text("x")
        _run(["add", "f.txt"], repo)
        _run(["commit", "-q", "-m", "first commit"], repo)
        context = git_context(repo)
        assert "Branch:" in context
        assert "first commit" in context

    def test_not_a_repo_is_empty(self, tmp_path: Path):
        assert git_context(tmp_path) == ""
