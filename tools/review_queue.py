#!/usr/bin/env python3
"""
Human review CLI for the manual-review queue.

SAFETY DISCIPLINE
=================
  * overnight/needs_manual_review.json is opened READ-ONLY here and is
    NEVER modified by this tool.
  * Only overnight/manual_review_decisions.jsonl is written, and only
    in append mode, and only when --confirm is passed.
  * Without --confirm, --approve and --reject are dry-runs: they print
    what would be written and exit 0.
  * No subprocess, no network, no env mutation.

INTENT
======
Present the 137-item manual review queue in a readable, filterable form
and record approve/reject decisions in an append-only log so the rest of
the pipeline can act on them.

Usage
-----
    review_queue.py                       summary
    review_queue.py --list                pending items
    review_queue.py --list --all          include already-decided items
    review_queue.py --list --by-file      grouped by file
    review_queue.py --list --by-category  grouped by category
    review_queue.py --show <id>           detailed view
    review_queue.py --approve <id> --confirm
    review_queue.py --reject  <id> --confirm [--reason TEXT]
    review_queue.py --decisions           decision log
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = REPO_ROOT / "overnight" / "needs_manual_review.json"
DECISIONS_PATH = REPO_ROOT / "overnight" / "manual_review_decisions.jsonl"


# ---------------------------------------------------------------------------
# I/O (read-only for queue, append-only for decisions)
# ---------------------------------------------------------------------------
def load_queue() -> list[dict]:
    """Read needs_manual_review.json. Never writes."""
    if not QUEUE_PATH.is_file():
        return []
    try:
        with open(QUEUE_PATH, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def load_decisions() -> list[dict]:
    """Read manual_review_decisions.jsonl. Returns [] if missing."""
    if not DECISIONS_PATH.is_file():
        return []
    out: list[dict] = []
    try:
        with open(DECISIONS_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def append_decision(record: dict) -> None:
    """Append a decision. Only called when --confirm is set."""
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Item identity
# ---------------------------------------------------------------------------
def item_id(item: dict) -> str:
    """Stable short id: mr-<10 hex>. Based on file + description."""
    file = str(item.get("file", ""))
    issue = item.get("issue") or {}
    desc = str(issue.get("description", "")) if isinstance(issue, dict) else ""
    h = hashlib.sha256(f"{file}|{desc}".encode("utf-8")).hexdigest()[:10]
    return f"mr-{h}"


def decision_index(decisions: list[dict]) -> dict[str, dict]:
    """Latest decision per id."""
    out: dict[str, dict] = {}
    for d in decisions:
        iid = d.get("id")
        if isinstance(iid, str):
            out[iid] = d  # last write wins
    return out


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def truncate(s: Any, n: int = 80) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def print_summary() -> None:
    queue = load_queue()
    decisions = load_decisions()
    idx = decision_index(decisions)

    total = len(queue)
    decided_ids = set(idx.keys())
    pending = [q for q in queue if item_id(q) not in decided_ids]
    approved = sum(1 for d in decisions if d.get("decision") == "approve")
    rejected = sum(1 for d in decisions if d.get("decision") == "reject")

    print("=" * 72)
    print("MANUAL REVIEW QUEUE")
    print("=" * 72)
    print(f"  Queue file:      {QUEUE_PATH.relative_to(REPO_ROOT)}")
    print(f"  Decisions file:  {DECISIONS_PATH.relative_to(REPO_ROOT)}")
    print()
    print(f"  Total in queue:  {total}")
    print(f"  Pending review:  {len(pending)}")
    print(f"  Already decided: {len(decided_ids)}")
    print(f"    approved:      {approved}")
    print(f"    rejected:      {rejected}")
    print()

    if pending:
        cats = Counter(
            str((p.get("issue") or {}).get("category", "unknown")) for p in pending
        )
        print("  Pending by category:")
        for c, n in cats.most_common():
            print(f"    {n:>4}  {c}")
        print()
        files = Counter(str(p.get("file", "?")) for p in pending)
        print(f"  Top pending files ({len(files)} unique):")
        for f, n in files.most_common(8):
            print(f"    {n:>4}  {f}")


def print_list(include_all: bool, by: str | None) -> None:
    queue = load_queue()
    decisions = load_decisions()
    idx = decision_index(decisions)

    rows: list[tuple[str, dict, dict | None]] = []
    for item in queue:
        iid = item_id(item)
        d = idx.get(iid)
        if not include_all and d is not None:
            continue
        rows.append((iid, item, d))

    if not rows:
        print("No items to display.")
        return

    if by == "file":
        grouped: dict[str, list[tuple[str, dict, dict | None]]] = defaultdict(list)
        for r in rows:
            grouped[str(r[1].get("file", "?"))].append(r)
        for file in sorted(grouped.keys()):
            print()
            print(f"=== {file}  ({len(grouped[file])} items) ===")
            for iid, item, d in grouped[file]:
                _print_row(iid, item, d)
        return

    if by == "category":
        grouped = defaultdict(list)
        for r in rows:
            cat = str((r[1].get("issue") or {}).get("category", "unknown"))
            grouped[cat].append(r)
        for cat in sorted(grouped.keys()):
            print()
            print(f"=== {cat}  ({len(grouped[cat])} items) ===")
            for iid, item, d in grouped[cat]:
                _print_row(iid, item, d)
        return

    # flat
    print(f"{'ID':<14}  {'STATUS':<8}  {'CATEGORY':<22}  {'FILE':<40}  REASON")
    print("-" * 140)
    for iid, item, d in rows:
        status = d.get("decision", "pending") if d else "pending"
        _print_row(iid, item, None, status=status)


def _print_row(iid: str, item: dict, decision: dict | None, status: str = "") -> None:
    if not status:
        status = decision.get("decision", "pending") if decision else "pending"
    issue = item.get("issue") or {}
    cat = str(issue.get("category", "?")) if isinstance(issue, dict) else "?"
    file = truncate(item.get("file", "?"), 40)
    reason = truncate(item.get("deferred_reason", ""), 60)
    print(f"{iid:<14}  {status:<8}  {cat:<22}  {file:<40}  {reason}")


def print_show(iid: str) -> int:
    queue = load_queue()
    decisions = load_decisions()
    idx = decision_index(decisions)

    item = next((q for q in queue if item_id(q) == iid), None)
    if item is None:
        print(f"No item with id {iid!r}", file=sys.stderr)
        return 1

    issue = item.get("issue") or {}
    print("=" * 72)
    print(f"ID:           {iid}")
    print(f"File:         {item.get('file', '?')}")
    print(f"Category:     {issue.get('category', '?') if isinstance(issue, dict) else '?'}")
    print(f"Severity:     {issue.get('severity', '?') if isinstance(issue, dict) else '?'}")
    print(f"Escalated at: {item.get('escalated_at', '?')}")
    print(f"Reason:       {item.get('deferred_reason', '?')}")
    print()
    if isinstance(issue, dict):
        print(f"Issue description:")
        print(f"  {issue.get('description', '(none)')}")
        if issue.get("suggestion"):
            print(f"Suggestion:")
            print(f"  {issue.get('suggestion')}")
        if issue.get("line_start"):
            print(f"Lines: {issue.get('line_start')}–{issue.get('line_end')}")
    print()
    d = idx.get(iid)
    if d:
        print(f"Decision already recorded:")
        print(f"  decision:    {d.get('decision')}")
        print(f"  reviewed_at: {d.get('reviewed_at')}")
        print(f"  reviewer:    {d.get('reviewer', '?')}")
        if d.get("reason"):
            print(f"  reason:      {d.get('reason')}")
    else:
        print("Decision:    (pending)")
    return 0


def record(iid: str, decision: str, reason: str, confirm: bool) -> int:
    if decision not in ("approve", "reject"):
        print(f"Invalid decision: {decision!r}", file=sys.stderr)
        return 2

    queue = load_queue()
    item = next((q for q in queue if item_id(q) == iid), None)
    if item is None:
        print(f"No item with id {iid!r}", file=sys.stderr)
        return 1

    decisions = load_decisions()
    idx = decision_index(decisions)
    if iid in idx:
        print(f"Item {iid} already has a decision ({idx[iid].get('decision')}).")
        print("Refusing to overwrite. Decisions log is append-only.")
        return 1

    issue = item.get("issue") or {}
    record = {
        "id": iid,
        "decision": decision,
        "reason": reason or "",
        "reviewer": "human",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "file": item.get("file", ""),
        "category": issue.get("category") if isinstance(issue, dict) else None,
        "issue_description": issue.get("description") if isinstance(issue, dict) else None,
        "deferred_reason": item.get("deferred_reason", ""),
    }

    if not confirm:
        print("DRY RUN — would append this decision:")
        print(json.dumps(record, indent=2, sort_keys=True))
        print()
        print("Re-run with --confirm to write.")
        return 0

    append_decision(record)
    print(f"Recorded: {iid} -> {decision}")
    print(f"Appended to: {DECISIONS_PATH.relative_to(REPO_ROOT)}")
    return 0


def print_decisions() -> None:
    decisions = load_decisions()
    if not decisions:
        print("(no decisions recorded yet)")
        return
    print(f"{'ID':<14}  {'DECISION':<8}  {'REVIEWED AT':<28}  FILE")
    print("-" * 100)
    for d in decisions:
        print(
            f"{str(d.get('id', '?')):<14}  "
            f"{str(d.get('decision', '?')):<8}  "
            f"{truncate(d.get('reviewed_at', '?'), 28):<28}  "
            f"{truncate(d.get('file', '?'), 40)}"
        )
        if d.get("reason"):
            print(f"    reason: {truncate(d['reason'], 100)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="review_queue",
        description="Human review CLI for the manual review queue (append-only decisions).",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true", help="list queue items")
    g.add_argument("--show", metavar="ID", help="show one item in detail")
    g.add_argument("--approve", metavar="ID", help="record an approval decision")
    g.add_argument("--reject", metavar="ID", help="record a rejection decision")
    g.add_argument("--decisions", action="store_true", help="print the decisions log")
    parser.add_argument("--all", action="store_true", help="with --list, include decided items")
    parser.add_argument(
        "--by",
        choices=["file", "category"],
        help="with --list, group output",
    )
    parser.add_argument("--reason", default="", help="reason for approve/reject")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually write the decision. Without it, dry-run only.",
    )
    args = parser.parse_args(argv)

    if args.list:
        print_list(include_all=args.all, by=args.by)
        return 0

    if args.show:
        return print_show(args.show)

    if args.approve:
        return record(args.approve, "approve", args.reason, args.confirm)

    if args.reject:
        return record(args.reject, "reject", args.reason, args.confirm)

    if args.decisions:
        print_decisions()
        return 0

    print_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
