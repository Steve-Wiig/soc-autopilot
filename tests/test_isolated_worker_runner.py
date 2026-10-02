from pathlib import Path
import os
import tempfile
import subprocess
from engine.isolated_worker_runner import execute_worker_in_isolation

def test_execute_worker_in_isolation():
    # Create a temporary directory to use as the repository root
    with tempfile.TemporaryDirectory() as repo_root:
        repo_path = Path(repo_root)

        # Initialize a git repo and make an initial commit so worktree add works
        subprocess.run(['git', 'init'], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=repo_path, check=True, capture_output=True)
        (repo_path / "dummy.txt").write_text("dummy")
        subprocess.run(['git', 'add', 'dummy.txt'], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'init'], cwd=repo_path, check=True, capture_output=True)

        # Define a worker function that creates a file in the worktree
        def worker_callable(worktree_path):
            file_path = worktree_path / "test_file.txt"
            file_path.write_text("Hello, world!")
            return file_path.name  # Return the filename to prove execution

        # Execute the worker function in isolation
        result = execute_worker_in_isolation(repo_path, worker_callable)
        
        # 1. Verify the worker executed and returned the expected result
        assert result == "test_file.txt"
        
        # 2. CRITICAL: Verify the canonical repo was NOT mutated!
        # The worktree is cleaned up on exit, so the file must NOT exist in the main repo.
        assert not (repo_path / "test_file.txt").exists()

if __name__ == '__main__':
    test_execute_worker_in_isolation()
