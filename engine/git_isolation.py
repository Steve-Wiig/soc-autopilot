"""
P0 Isolation: Git Worktree Primitives.
Provides a context manager to run operations in an isolated worktree,
ensuring the operator's canonical working tree is never mutated.
"""
import subprocess
from pathlib import Path
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def run_in_worktree(repo_root: Path, branch_name: str, base_ref: str = "HEAD") -> Iterator[Path]:
    """
    Creates a temporary git worktree, yields its path, and cleans it up on exit.

    This ensures that any operations performed within the `with` block run
    against an isolated checkout, leaving the operator's canonical working
    tree untouched.

    Args:
        repo_root: Path to the root of the canonical git repository.
        branch_name: Name of the new branch to create for this worktree.
        base_ref: The git ref (branch, tag, or commit) to base the new
            worktree/branch on. Defaults to "HEAD".

    Yields:
        Path: The filesystem path to the newly created worktree directory.

    Note:
        Cleanup (worktree removal and branch deletion) is best-effort:
        failures during cleanup are intentionally suppressed so that they
        do not mask exceptions raised by the caller's code inside the
        `with` block.
    """
    worktree_dir = repo_root / ".worktrees" / branch_name
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Create the isolated worktree on a new branch based on `base_ref`.
        # capture_output=True keeps git's stdout/stderr out of the caller's
        # console; check=True ensures failures raise CalledProcessError.
        subprocess.run(
            ["git", "worktree", "add", str(worktree_dir), "-b", branch_name, base_ref],
            cwd=repo_root, check=True, capture_output=True
        )
        yield worktree_dir
    finally:
        # Best-effort cleanup: remove the worktree and delete its branch.
        # Errors here are deliberately not raised (no check=True) to avoid
        # masking exceptions from the `with` block or failing on partial state.
        subprocess.run(["git", "worktree", "remove", str(worktree_dir), "--force"], cwd=repo_root, capture_output=True)
        subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_root, capture_output=True)
