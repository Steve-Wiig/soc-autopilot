"""
P0-3 Execution: Isolated Worker Runner.
Forces development workers to execute strictly within an isolated Git worktree.
The operator's canonical working tree is never mutated.
"""
import uuid
from pathlib import Path
from typing import Callable, Any
from engine.git_isolation import run_in_worktree

def execute_worker_in_isolation(
    repo_root: Path, 
    worker_callable: Callable[[Path], Any], 
    base_ref: str = "HEAD"
) -> Any:
    """
    Spins up an isolated worktree, runs the worker inside it, 
    and guarantees cleanup even if the worker crashes.
    """
    # Generate a unique branch name for this isolated run
    branch_name = f"isolated/worker-{uuid.uuid4().hex[:8]}"
    
    with run_in_worktree(repo_root, branch_name, base_ref) as worktree_path:
        # The worker callable MUST accept the worktree path as its first argument
        # and operate strictly within that directory.
        return worker_callable(worktree_path)
