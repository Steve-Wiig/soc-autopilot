#!/usr/bin/env python3
"""
Read-only audit: needs_manual_review.json inventory.

SAFETY DISCIPLINE
  * Path.read_text() only.
  * No writes, no subprocess, no network.
  * stdout only.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


if __name__ != "__main__":
    raise RuntimeError("diagnostic; run as main")


REPO_ROOT = Path(__file__).resolve().parent.parent
NMR = REPO_ROOT / "overnight" / "needs_manual_review.json"
DEF = REPO_ROOT / "overnight" / "fix_backlog_deferred.json"


def header(t: str) -> None:
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


def sub(t: str) -> None:
    print()
    print(f"--- {t} ---")


def read_json(p: Path):
    if not p.is_file():
        return None, None
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        return json.loads(raw), raw
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)


def truncate(s, n=110):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def audit_file(p: Path, label: str) -> None:
    header(f"FILE: {label}")
    print(f"  path: {p.relative_to(REPO_ROOT)}")
    data, raw = read_json(p)
    if data is None:
        print(f"  status: MISSING or UNREADABLE ({raw})")
        return
    if isinstance(data, list):
        print(f"  type: list of {len(data)}")
        # Category distribution
        cats = Counter()
        files = Counter()
        reasons = Counter()
        severities = Counter()
        for item in data:
            if not isinstance(item, dict):
                continue
            issue = item.get("issue") or {}
            if isinstance(issue, dict):
                cats[str(issue.get("category", "?"))] += 1
                severities[str(issue.get("severity", "?"))] += 1
            files[str(item.get("file", "?"))] += 1
            reasons[str(item.get("deferred_reason", "?"))] += 1

        sub("category distribution")
        for c, n in cats.most_common():
            print(f"  {n:>4}  {c}")

        sub("severity distribution")
        for s, n in severities.most_common():
            print(f"  {n:>4}  {s}")

        sub("deferred_reason distribution")
        for r, n in reasons.most_common():
            print(f"  {n:>4}  {truncate(r, 100)}")

        sub(f"file distribution (top 15 of {len(files)})")
        for f, n in files.most_common(15):
            print(f"  {n:>4}  {f}")

        sub("first 5 entries (structure)")
        for i, item in enumerate(data[:5]):
            if isinstance(item, dict):
                keys = sorted(item.keys())
                print(f"  [{i}] keys={keys}")
                issue = item.get("issue") or {}
                if isinstance(issue, dict):
                    desc = truncate(issue.get("description", ""), 90)
                    print(f"       file={item.get('file', '?')}")
                    print(f"       desc={desc}")
                    print(f"       reason={truncate(item.get('deferred_reason', ''), 100)}")
            else:
                print(f"  [{i}] non-dict: {type(item).__name__}")
    elif isinstance(data, dict):
        print(f"  type: dict, keys={sorted(data.keys())[:20]}")
    else:
        print(f"  type: {type(data).__name__}")


def main() -> int:
    print("soc-autopilot :: read-only manual review audit")
    print(f"repo root: {REPO_ROOT}")

    audit_file(NMR, "needs_manual_review.json")
    audit_file(DEF, "fix_backlog_deferred.json")

    header("SUMMARY")
    print("  All reads completed. No writes were performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
