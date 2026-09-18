#!/usr/bin/env python3
"""
DISABLED legacy feature builder.

This historical runner applied generated patches directly to the
canonical checkout and committed them automatically.

It is intentionally disabled pending redesign around disposable
worktrees and human-gated promotion.
"""

raise SystemExit(
    "DISABLED: scripts/build_feature.py is a legacy autonomous runner. "
    "Use the bounded proposal workflow instead."
)
