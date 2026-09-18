#!/usr/bin/env python3
"""
DISABLED legacy overnight runner.

This historical runner performed canonical-tree patch application,
broad cleanup, staging, and automatic commits.

It is intentionally disabled pending redesign around the bounded
development-worker path.
"""

raise SystemExit(
    "DISABLED: scripts/overnight_runner.py is a legacy autonomous runner. "
    "Use the bounded proposal workflow instead."
)
