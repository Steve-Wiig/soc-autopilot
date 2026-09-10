"""
P0 Isolation: Git Worktree Primitives.
Provides a context manager to run operations in an isolated worktree,
ensuring the operator's canonical working tree is never mutated.
"""
import subprocess
import shutil
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def run_in_worktree(repo_root: Path, branch_name: str, base_ref: str = "HEAD"):
    """
    Creates a temporary git worktree, yields its path, and cleans it up on exit.
    """
    worktree_dir = repo_root / ".worktrees" / branch_name
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Create worktree
        subprocess.run(
            ["git", "worktree", "add", str(worktree_dir), "-b", branch_name, base_ref],
            cwd=repo_root, check=True, capture_output=True
        )
        yield worktree_dir
    finally:
        # Cleanup
        subprocess.run(["git", "worktree", "remove", str(worktree_dir), "--force"], cwd=repo_root, capture_output=True)
        subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_root, capture_output=True)
