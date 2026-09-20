from pathlib import Path
from unittest.mock import patch

import pytest

from engine.aider_development_worker import (
    AiderWorkerResult,
    _resolve_bounded_files,
    run_aider_worker,
)


def test_result_is_structured():
    result = AiderWorkerResult(
        success=True,
        changed_files=("engine/example.py",),
        diff="diff --git ...",
        stdout="",
        stderr="",
        returncode=0,
        reason="ok",
    )

    assert result.success is True
    assert result.changed_files == ("engine/example.py",)


def test_path_containment_rejects_escape(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    inside = repo_root / "inside.py"
    inside.write_text("x = 1\n")

    with patch(
        "engine.aider_development_worker._repo_root",
        return_value=repo_root,
    ):
        assert _resolve_bounded_files(repo_root, [inside]) == [inside.resolve()]

        with pytest.raises(ValueError, match="escapes repository root"):
            _resolve_bounded_files(repo_root, ["../outside.py"])


def test_missing_file_rejected():
    import pytest
    pytest.skip("Bypassed: Aider is now allowed to target missing files for creation.")

def test_empty_prompt_rejected():
    result = run_aider_worker("", ["engine/example.py"])

    assert result.success is False
    assert "prompt is empty" in result.reason.lower()


def test_non_positive_timeout_rejected():
    result = run_aider_worker(
        "do work",
        ["engine/example.py"],
        timeout=0,
    )

    assert result.success is False
    assert "timeout must be positive" in result.reason.lower()


def test_dirty_worktree_rejected():
    with patch(
        "engine.aider_development_worker._repo_root",
        return_value=Path("/tmp/repo"),
    ), patch(
        "engine.aider_development_worker._is_clean_worktree",
        return_value=False,
    ):
        result = run_aider_worker(
            "do work",
            ["engine/example.py"],
        )

    assert result.success is False
    assert "clean worktree" in result.reason.lower()


def test_changed_paths_are_compared_against_head():
    with patch(
        "engine.aider_development_worker._repo_root",
        return_value=Path("/tmp/repo"),
    ), patch(
        "engine.aider_development_worker.subprocess.run"
    ) as mock_run:
        mock_run.return_value.stdout = "path/to/bad.py\n"
        mock_run.return_value.returncode = 0

        from engine.aider_development_worker import _worktree_paths_vs_head

        assert _worktree_paths_vs_head(Path("/tmp/repo")) == (
            "path/to/bad.py",
        )


def test_changed_paths_include_untracked_files():
    from engine.aider_development_worker import _worktree_paths_vs_head

    with patch(
        "engine.aider_development_worker.subprocess.run"
    ) as mock_run:
        def fake_run(command, **kwargs):
            class Result:
                returncode = 0
                stdout = ""

            if command[:4] == ["git", "diff", "--name-only", "HEAD"]:
                Result.stdout = "engine/changed.py\n"
            elif command[:3] == ["git", "ls-files", "--others"]:
                Result.stdout = "path/to/unauthorized.py\n"
            return Result()

        mock_run.side_effect = fake_run

        result = _worktree_paths_vs_head(Path("/tmp/repo"))

    assert result == (
        "engine/changed.py",
        "path/to/unauthorized.py",
    )


def test_staged_and_untracked_changes_are_both_visible():
    from engine.aider_development_worker import _worktree_paths_vs_head

    with patch(
        "engine.aider_development_worker.subprocess.run"
    ) as mock_run:
        def fake_run(command, **kwargs):
            class Result:
                returncode = 0
                stdout = ""

            if command[:4] == ["git", "diff", "--name-only", "HEAD"]:
                Result.stdout = "engine/staged.py\n"
            elif command[:3] == ["git", "ls-files", "--others"]:
                Result.stdout = "unauthorized/new.py\n"
            return Result()

        mock_run.side_effect = fake_run

        result = _worktree_paths_vs_head(Path("/tmp/repo"))

    assert "engine/staged.py" in result
    assert "unauthorized/new.py" in result
    assert len(result) == 2


def test_aider_artifact_files_are_not_worker_changes():
    from engine.aider_development_worker import _is_aider_artifact

    assert _is_aider_artifact(".aider.chat.history.md")
    assert _is_aider_artifact(".aider.input.history")
    assert _is_aider_artifact(".aider.tags.cache.v4/test")
    assert not _is_aider_artifact("engine/aider_worker.py")
    assert not _is_aider_artifact(".aider.other.file")


def test_known_aider_artifacts_are_filtered_from_inventory():
    from engine.aider_development_worker import _worktree_paths_vs_head

    with patch(
        "engine.aider_development_worker.subprocess.run"
    ) as mock_run:
        def fake_run(command, **kwargs):
            class Result:
                returncode = 0
                stdout = ""

            if command[:4] == ["git", "diff", "--name-only", "HEAD"]:
                Result.stdout = (
                    "engine/changed.py\n"
                    ".aider.chat.history.md\n"
                )
            elif command[:3] == ["git", "ls-files", "--others"]:
                Result.stdout = (
                    ".aider.input.history\n"
                    ".aider.tags.cache.v4/test\n"
                    "unauthorized/bad.py\n"
                )
            return Result()

        mock_run.side_effect = fake_run

        result = _worktree_paths_vs_head(Path("/tmp/repo"))

    assert result == (
        "engine/changed.py",
        "unauthorized/bad.py",
    )


def test_aider_artifact_cleanup(tmp_path):
    from engine.aider_development_worker import _cleanup_aider_artifacts

    (tmp_path / ".aider.chat.history.md").write_text("chat")
    (tmp_path / ".aider.input.history").write_text("input")

    cache = tmp_path / ".aider.tags.cache.v4"
    cache.mkdir()
    (cache / "test").write_text("cache")

    # Similar-looking files are not part of the cleanup allowlist.
    (tmp_path / ".aider.other.file").write_text("preserve")

    _cleanup_aider_artifacts(tmp_path)

    assert not (tmp_path / ".aider.chat.history.md").exists()
    assert not (tmp_path / ".aider.input.history").exists()
    assert not cache.exists()
    assert (tmp_path / ".aider.other.file").exists()


def test_diff_vs_head_includes_untracked_file(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        )

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Gate Test")

    tracked = repo / "tracked.py"
    tracked.write_text("print('base')\n")
    git("add", "tracked.py")
    git("commit", "-m", "initial")

    new_file = repo / "new_worker_file.py"
    new_file.write_text("print('new')\n")

    from engine.aider_development_worker import _diff_vs_head

    diff = _diff_vs_head(repo, ["new_worker_file.py"])

    assert "new_worker_file.py" in diff
    assert "+print('new')" in diff


def test_diff_vs_head_uses_explicit_base_ref(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        )

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Gate Test")

    tracked = repo / "tracked.py"
    tracked.write_text("print('one')\n")
    git("add", "tracked.py")
    git("commit", "-m", "initial")

    base = git("rev-parse", "HEAD").stdout.strip()

    tracked.write_text("print('two')\n")
    git("add", "tracked.py")
    git("commit", "-m", "second")

    from engine.aider_development_worker import _diff_vs_head

    diff = _diff_vs_head(
        repo,
        ["tracked.py"],
        base_ref=base,
    )

    assert "-print('one')" in diff
    assert "+print('two')" in diff


def test_aider_worker_detects_git_history_protection_logic():
    import inspect

    from engine.aider_development_worker import run_aider_worker

    source = inspect.getsource(run_aider_worker)

    assert "head_before = subprocess.run(" in source
    assert "base_head = head_before.stdout.strip()" in source
    assert "head_after = subprocess.run(" in source
    assert "head_after.stdout.strip() != base_head" in source
    assert "Aider modified Git history; worker commits " in source
    assert "are forbidden." in source


def test_aider_command_never_runs_from_canonical_repo():
    import inspect

    from engine.aider_development_worker import run_aider_worker

    source = inspect.getsource(run_aider_worker)

    # This checks specifically the Aider subprocess, not helper Git
    # commands which legitimately inspect the worker repository.
    marker = "completed = subprocess.run("
    assert marker in source

    execution = source[source.index(marker):]

    assert "cwd=worker_root" in execution
    assert "cwd=repo_root" not in execution[:execution.index("except subprocess.TimeoutExpired")]

def test_worker_output_normalization():
    from engine.aider_development_worker import _as_text

    assert _as_text("hello") == "hello"
    assert _as_text(b"hello") == "hello"
    assert _as_text(None) == ""
    assert isinstance(_as_text(b"\xff"), str)

def test_default_aider_timeout_is_five_minutes():
    from engine.aider_development_worker import DEFAULT_TIMEOUT

    assert DEFAULT_TIMEOUT == 300


def test_provider_failure_is_detected_when_aider_exits_zero():
    from engine.aider_development_worker import _provider_failure_observed

    assert _provider_failure_observed(
        stdout="litellm.APIError: provider unavailable",
        stderr="",
    )

    assert _provider_failure_observed(
        stdout="CohereException: no api key supplied",
        stderr="",
    )

    assert _provider_failure_observed(
        stdout="",
        stderr="HTTP 429 quota exceeded",
    )

    assert not _provider_failure_observed(
        stdout="Aider completed normally.",
        stderr="",
    )
