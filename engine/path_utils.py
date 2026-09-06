#!/usr/bin/env python3
"""Utility to determine the repository root."""

from pathlib import Path

def get_repo_root() -> Path:
    """
    Return the absolute path to the repository root.
    Assumes this file is in engine/ subdirectory.
    """
    return Path(__file__).resolve().parents[1]

# Optional: if called as script, print the root
if __name__ == "__main__":
    print(get_repo_root())
