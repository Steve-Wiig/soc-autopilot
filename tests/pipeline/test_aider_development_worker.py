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


def test_missing_file_rejected(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with pytest.raises(FileNotFoundError):
        _resolve_bounded_files(repo_root, ["missing.py"])


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
