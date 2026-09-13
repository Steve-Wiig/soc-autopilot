#!/usr/bin/env python3
"""
Read-only audit: every NAS reference and every Oracle-path reference.

SAFETY DISCIPLINE
  * Path.read_text() only.
  * No writes, no subprocess, no network.
  * stdout only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


if __name__ != "__main__":
    raise RuntimeError("diagnostic; run as main")


REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}
SKIP_SUFFIX = {".pyc", ".pyo", ".so", ".o", ".bin", ".sqlite", ".db"}
SKIP_PATTERNS = (".bak",)

PATTERNS = [
    (re.compile(r"/mnt/backup-nas"), "NAS mount path"),
    (re.compile(r"\bNAS_[A-Z_]+\b"), "NAS_* constant"),
    (re.compile(r"\bNAS_BASE\b"), "NAS_BASE symbol"),
    (re.compile(r"nas_aware_"), "nas_aware_* helper"),
    (re.compile(r"\bto NAS\b"), "false 'to NAS' telemetry"),
    (re.compile(r"\bevacuat"), "evacuation logic"),
    (re.compile(r"\bbackup-nas\b"), "backup-nas name"),
]


def should_skip(p: Path) -> bool:
    if p.suffix in SKIP_SUFFIX:
        return True
    if any(s in p.name for s in SKIP_PATTERNS):
        return True
    return any(part in SKIP_DIRS for part in p.parts)


def main() -> int:
    print("soc-autopilot :: read-only NAS reference audit")
    print(f"repo root: {REPO_ROOT}")
    print()

    hits_by_pattern = {label: [] for _, label in PATTERNS}
    files_scanned = 0
    files_with_hits = set()

    for p in sorted(REPO_ROOT.rglob("*")):
        if not p.is_file():
            continue
        if should_skip(p):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        files_scanned += 1
        rel = p.relative_to(REPO_ROOT)
        for i, line in enumerate(text.splitlines(), 1):
            for rx, label in PATTERNS:
                if rx.search(line):
                    hits_by_pattern[label].append((rel, i, line.strip()[:140]))
                    files_with_hits.add(rel)

    print(f"files scanned: {files_scanned}")
    print(f"files with hits: {len(files_with_hits)}")
    print()

    for _, label in PATTERNS:
        hits = hits_by_pattern[label]
        if not hits:
            continue
        print(f"=== {label} ({len(hits)} hits) ===")
        for rel, line_no, line in hits:
            print(f"  {rel}:{line_no}  {line}")
        print()

    print("=== files with any hit ===")
    for f in sorted(files_with_hits):
        print(f"  {f}")

    print()
    print("All reads completed. No writes were performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
