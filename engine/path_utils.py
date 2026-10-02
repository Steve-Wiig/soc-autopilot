#!/usr/bin/env python3
"""Utility to determine the repository root."""

from pathlib import Path

# This file lives one directory below the repository root
# (i.e., repo_root/engine/path_utils.py), so we need to go
# up exactly one parent level to reach the repo root.
_ENGINE_DIR_DEPTH = 1


def get_repo_root() -> Path:
    """
    Return the absolute path to the repository root.

    Assumes this file is located in the `engine/` subdirectory,
    one level below the repository root.

    Returns:
        Path: The absolute path to the repository root directory.
    """
    return Path(__file__).resolve().parents[_ENGINE_DIR_DEPTH]


if __name__ == "__main__":
    # When run as a script, print the resolved repository root path.
    print(get_repo_root())
