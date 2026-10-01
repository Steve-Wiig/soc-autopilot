import os
import tempfile
from engine.isolated_worker_runner import execute_worker_in_isolation

def test_execute_worker_in_isolation():
    # Create a temporary directory to use as the repository root
    with tempfile.TemporaryDirectory() as repo_root:
        # Define a worker function that creates a file in the worktree
        def worker_callable(worktree_path):
            file_path = worktree_path / "test_file.txt"
            file_path.write_text("Hello, world!")
            return file_path

        # Execute the worker function in isolation
        result_path = execute_worker_in_isolation(Path(repo_root), worker_callable)

        # Verify that the file was created in the worktree
        assert result_path.exists()
        assert result_path.read_text() == "Hello, world!"

if __name__ == '__main__':
    test_execute_worker_in_isolation()
