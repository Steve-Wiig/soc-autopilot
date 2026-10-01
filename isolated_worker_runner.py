"""
P0-3 Execution: Isolated Worker Runner.
Forces development workers to execute strictly within an isolated Git worktree.
The operator's canonical working tree is never mutated.
"""
import uuid
from pathlib import Path
from typing import Callable, TypeVar
from engine.git_isolation import run_in_worktree

WorkerResult = TypeVar("WorkerResult")

ISOLATED_BRANCH_PREFIX = "isolated/worker-"


def execute_worker_in_isolation(
    repo_root: Path,
    worker_callable: Callable[[Path], WorkerResult],
    base_ref: str = "HEAD",
) -> WorkerResult:
    """
    Spin up an isolated worktree, run the worker inside it, and guarantee
    cleanup even if the worker raises an exception.

    Args:
        repo_root: Path to the root of the canonical Git repository.
        worker_callable: A callable that performs work strictly within the
            isolated worktree. It MUST accept the worktree path as its only
            argument and MUST NOT read from or write to any path outside it.
        base_ref: The Git ref (branch, tag, or commit) the isolated worktree
            should be based on. Defaults to "HEAD".

    Returns:
        Whatever `worker_callable` returns.

    Note:
        The operator's canonical working tree is never mutated; all work
        happens on a uniquely named, disposable branch inside a temporary
        worktree.
    """
    # Generate a unique branch name for this isolated run
    branch_name = f"{ISOLATED_BRANCH_PREFIX}{uuid.uuid4().hex[:8]}"

    with run_in_worktree(repo_root, branch_name, base_ref) as worktree_path:
        # The worker callable MUST accept the worktree path as its first argument
        # and operate strictly within that directory.
        return worker_callable(worktree_path)
