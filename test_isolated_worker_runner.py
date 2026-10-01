import pytest
from pathlib import Path
from engine.isolated_worker_runner import execute_worker_in_isolation

def test_execute_worker_in_isolation():
    repo_root = Path("/path/to/repo")
    base_ref = "HEAD"

    def worker_callable(worktree_path: Path) -> str:
        return f"Work done in {worktree_path}"

    result = execute_worker_in_isolation(repo_root, worker_callable, base_ref)
    assert result == "Work done in /path/to/repo/.git/isolated/worker-<uuid>"
