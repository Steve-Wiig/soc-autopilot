#!/usr/bin/env python3
"""Read-only dashboard fact-check.

Compares what the dashboard prints to what the raw files contain.
No writes, no subprocess, stdout only.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OV = ROOT / "overnight"

def read_jsonl(p):
    if not p.is_file(): return []
    out = []
    for line in p.read_text(errors="replace").splitlines():
        if line.strip():
            try: out.append(json.loads(line))
            except json.JSONDecodeError: pass
    return out

def read_json(p):
    if not p.is_file(): return None
    try: return json.loads(p.read_text(errors="replace"))
    except Exception: return None

print("=" * 60)
print("DASHBOARD FACT-CHECK")
print("=" * 60)

# Ledger status counts
ledger = read_jsonl(OV / "improvement_ledger.jsonl")
statuses = Counter(r.get("status") for r in ledger)
print(f"\nLedger total: {len(ledger)}")
for s, n in statuses.most_common():
    print(f"  {s:<28} {n}")

# Backlog
backlog = read_json(OV / "fix_backlog.json")
deferred = read_json(OV / "fix_backlog_deferred.json")
print(f"\nfix_backlog.json:          {len(backlog) if isinstance(backlog, list) else 'unreadable'}")
print(f"fix_backlog_deferred.json: {len(deferred) if isinstance(deferred, list) else 'unreadable'}")

# Manual review queue
queue = read_json(OV / "needs_manual_review.json")
print(f"needs_manual_review.json:  {len(queue) if isinstance(queue, list) else 'unreadable'}")

# Decisions
decisions_path = OV / "manual_review_decisions.jsonl"
decisions = read_jsonl(decisions_path)
print(f"manual_review_decisions:   {len(decisions)}")

# TDD queue
tdd = read_jsonl(OV / "tdd_eval_queue.jsonl")
print(f"tdd_eval_queue:            {len(tdd)}")

# Proven / failed
proven = read_jsonl(OV / "proven_fixes.jsonl")
failed = read_jsonl(OV / "failed_fixes.jsonl")
print(f"proven_fixes:              {len(proven)}")
print(f"failed_fixes:              {len(failed)}")

# Success rate reproductions
applied = statuses.get("APPLIED", 0)
rejected = statuses.get("REJECTED", 0)
escalated = statuses.get("ESCALATED", 0)
stale = statuses.get("STALE", 0)
tdd_eval = statuses.get("TDD_EVALUATED", 0)
deferred_status = statuses.get("DEFERRED", 0)

print("\n" + "=" * 60)
print("SUCCESS RATE RECONCILIATION")
print("=" * 60)
cur = applied / (applied + rejected + escalated) * 100 if (applied + rejected + escalated) else 0
print(f"  Dashboard formula: {applied}/({applied}+{rejected}+{escalated}) = {cur:.1f}%")

inc_stale = applied / (applied + rejected + escalated + stale) * 100 if (applied + rejected + escalated + stale) else 0
print(f"  With stale:        {applied}/(+{stale}) = {inc_stale:.1f}%")

inc_tdd = applied / (applied + rejected + escalated + tdd_eval) * 100 if (applied + rejected + escalated + tdd_eval) else 0
print(f"  With TDD_EVALUATED: {applied}/(+{tdd_eval}) = {inc_tdd:.1f}%")

print("\n" + "=" * 60)
print("CATEGORY x STATUS (from ledger)")
print("=" * 60)
matrix = {}
for r in ledger:
    c = r.get("category", "?")
    s = r.get("status", "?")
    matrix.setdefault(c, Counter())[s] += 1
for c in sorted(matrix):
    print(f"  {c}")
    for s, n in matrix[c].most_common():
        print(f"    {s:<28} {n}")

print("\nAll reads. No writes.")
