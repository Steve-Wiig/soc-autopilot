#!/usr/bin/env python3
"""
Read-only diagnostic phase 3: correlation analysis.

SAFETY DISCIPLINE (identical to phases 1-2)
  * Path.read_text() only; open(..., 'r') only.
  * SQLite via URI mode=ro + PRAGMA query_only.
  * No writes, no subprocess, no network, no env mutation.
  * stdout only.

INTENT
======
Correlate the four ledgers to answer:
  1. What are the actual ESCALATED reasons, ranked?
  2. What happened to TDD_EVALUATED records?
  3. Category x status matrix: where does each category get stuck?
  4. Time series: is the system making progress?
  5. Closure: for each escalated file, was a TDD_EVALUATED ever produced?
  6. Did failed_fixes.jsonl correlate with later escalations?

Run:
    python3 tools/analyze_escalations_readonly_v3.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


if __name__ != "__main__":
    raise RuntimeError("diagnostic script; run as main, do not import")


REPO_ROOT = Path(__file__).resolve().parent.parent
OVERNIGHT = REPO_ROOT / "overnight"
LEDGER = OVERNIGHT / "improvement_ledger.jsonl"
FAILED = OVERNIGHT / "failed_fixes.jsonl"
PROVEN = OVERNIGHT / "proven_fixes.jsonl"
TDD_QUEUE = OVERNIGHT / "tdd_eval_queue.jsonl"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def header(t: str) -> None:
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


def sub(t: str) -> None:
    print()
    print(f"--- {t} ---")


def kv(k: str, v: Any) -> None:
    print(f"  {k:<40} {v}")


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------
def read_jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    out: list[dict] = []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
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


def parse_ts(s: Any) -> datetime | None:
    if not isinstance(s, str):
        return None
    try:
        # ISO 8601, possibly with timezone
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def truncate(s: Any, n: int = 100) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def escalation_reasons(ledger: list[dict]) -> None:
    header("1. ESCALATED reasons, ranked")
    esc = [r for r in ledger if r.get("status") == "ESCALATED"]
    kv("total ESCALATED", len(esc))
    reasons = Counter(str(r.get("reason", "<missing>")).strip() for r in esc)
    print()
    for reason, n in reasons.most_common(30):
        pct = 100.0 * n / len(esc) if esc else 0.0
        print(f"  {n:>5}  {pct:>5.1f}%  {truncate(reason, 90)}")

    sub("ESCALATED by category")
    cats = Counter(str(r.get("category", "<missing>")) for r in esc)
    for c, n in cats.most_common():
        print(f"  {n:>5}  {c}")

    sub("ESCALATED by category x reason (top 20 pairs)")
    pairs = Counter(
        (str(r.get("category", "?")), str(r.get("reason", "?")))
        for r in esc
    )
    for (c, reason), n in pairs.most_common(20):
        print(f"  {n:>5}  {c:<24}  {truncate(reason, 70)}")


def tdd_evaluated_outcomes(ledger: list[dict]) -> None:
    header("2. TDD_EVALUATED outcomes")
    tdd = [r for r in ledger if r.get("status") == "TDD_EVALUATED"]
    kv("total TDD_EVALUATED", len(tdd))
    if not tdd:
        return

    sub("reason distribution")
    reasons = Counter(str(r.get("reason", "<missing>")).strip() for r in tdd)
    for reason, n in reasons.most_common(30):
        pct = 100.0 * n / len(tdd)
        print(f"  {n:>5}  {pct:>5.1f}%  {truncate(reason, 90)}")

    sub("category distribution")
    cats = Counter(str(r.get("category", "<missing>")) for r in tdd)
    for c, n in cats.most_common():
        print(f"  {n:>5}  {c}")

    sub("sample reasons (first 5 distinct)")
    seen = set()
    shown = 0
    for r in tdd:
        reason = str(r.get("reason", "")).strip()
        if reason and reason not in seen:
            seen.add(reason)
            print(f"  - {truncate(reason, 120)}")
            shown += 1
            if shown >= 5:
                break


def category_status_matrix(ledger: list[dict]) -> None:
    header("3. Category x status matrix")
    cats = sorted({str(r.get("category", "<missing>")) for r in ledger})
    statuses = sorted({str(r.get("status", "<missing>")) for r in ledger})
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for r in ledger:
        counts[(str(r.get("category", "<missing>")), str(r.get("status", "<missing>")))] += 1

    # Print as a table
    col_w = 14
    print(f"  {'category':<22}", end="")
    for s in statuses:
        print(f"{s[:col_w]:>{col_w}}", end="")
    print(f"{'TOTAL':>8}")
    for c in cats:
        row_total = 0
        print(f"  {c:<22}", end="")
        for s in statuses:
            n = counts.get((c, s), 0)
            row_total += n
            print(f"{n:>{col_w}}", end="")
        print(f"{row_total:>8}")
    print(f"  {'TOTAL':<22}", end="")
    for s in statuses:
        col_total = sum(counts.get((c, s), 0) for c in cats)
        print(f"{col_total:>{col_w}}", end="")
    print(f"{len(ledger):>8}")


def time_series(ledger: list[dict]) -> None:
    header("4. Time series — daily counts by status")
    by_day: dict[str, Counter] = defaultdict(Counter)
    for r in ledger:
        ts = parse_ts(r.get("timestamp"))
        if ts is None:
            continue
        day = ts.strftime("%Y-%m-%d")
        by_day[day][str(r.get("status", "?"))] += 1

    if not by_day:
        print("  no parseable timestamps")
        return

    days = sorted(by_day.keys())
    statuses = sorted({s for c in by_day.values() for s in c.keys()})
    col_w = 10
    print(f"  {'date':<12}", end="")
    for s in statuses:
        print(f"{s[:col_w]:>{col_w}}", end="")
    print(f"{'TOTAL':>8}")
    for d in days:
        row_total = sum(by_day[d].values())
        print(f"  {d:<12}", end="")
        for s in statuses:
            print(f"{by_day[d].get(s, 0):>{col_w}}", end="")
        print(f"{row_total:>8}")


def escalation_closure(ledger: list[dict], tdd_queue: list[dict]) -> None:
    header("5. Closure — did escalated files ever get a TDD test?")
    esc_files = {str(r.get("file", "")) for r in ledger if r.get("status") == "ESCALATED"}
    tdd_files = {str(r.get("file", "")) for r in tdd_queue}
    tdd_eval_files = {str(r.get("file", "")) for r in ledger if r.get("status") == "TDD_EVALUATED"}

    kv("unique files with any ESCALATED", len(esc_files))
    kv("unique files in tdd_eval_queue", len(tdd_files))
    kv("unique files with any TDD_EVALUATED", len(tdd_eval_files))

    overlap_queue = esc_files & tdd_files
    overlap_ledger = esc_files & tdd_eval_files
    kv("escalated files with a queued TDD (but stuck)", len(overlap_queue))
    kv("escalated files with a ledger TDD_EVALUATED", len(overlap_ledger))

    if overlap_queue:
        sub("sample (escalated AND queued for TDD)")
        for f in sorted(overlap_queue)[:10]:
            print(f"  - {f}")

    if overlap_ledger:
        sub("sample (escalated AND has a ledger TDD_EVALUATED)")
        for f in sorted(overlap_ledger)[:10]:
            print(f"  - {f}")


def repeated_failures(ledger: list[dict], failed: list[dict]) -> None:
    header("6. Repeated failure surfaces — files hit by both")
    failed_files = Counter(str(r.get("file", "")) for r in failed)
    esc_files = Counter(str(r.get("file", "")) for r in ledger if r.get("status") == "ESCALATED")

    both = {f for f in failed_files if f in esc_files}
    kv("files in both failed_fixes and ESCALATED", len(both))

    sub("top 15 files by escalations")
    for f, n in esc_files.most_common(15):
        mark = " *also failed*" if f in both else ""
        print(f"  {n:>5}  {f}{mark}")

    if failed_files:
        sub("top 15 files by failed fixes")
        for f, n in failed_files.most_common(15):
            mark = " *also escalated*" if f in both else ""
            print(f"  {n:>5}  {f}{mark}")


def failed_constraints(failed: list[dict]) -> None:
    header("7. Failed fix constraints (why the LLM failed)")
    kv("total failed_fixes records", len(failed))
    if not failed:
        return
    sub("category distribution")
    for c, n in Counter(str(r.get("category", "?")) for r in failed).most_common():
        print(f"  {n:>5}  {c}")

    sub("constraint strings (top 15, truncated)")
    constraints = Counter(truncate(str(r.get("constraint", "")).strip(), 120) for r in failed)
    for c, n in constraints.most_common(15):
        print(f"  {n:>5}  {c}")


def proven_patterns_detail(proven: list[dict]) -> None:
    header("8. Proven patterns — the 14 that work")
    kv("total proven patterns", len(proven))
    if not proven:
        return
    cats = Counter(str(r.get("category", "?")) for r in proven)
    sub("by category")
    for c, n in cats.most_common():
        print(f"  {n:>5}  {c}")

    sub("advisories")
    for r in proven:
        adv = truncate(str(r.get("advisory", "")).strip(), 110)
        f = r.get("file", "?")
        c = r.get("category", "?")
        print(f"  [{c:<22}] {f:<40} {adv}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print("soc-autopilot :: read-only escalation diagnostic phase 3 (correlation)")

    ledger = read_jsonl(LEDGER)
    failed = read_jsonl(FAILED)
    proven = read_jsonl(PROVEN)
    tdd_queue = read_jsonl(TDD_QUEUE)

    kv("ledger records", len(ledger))
    kv("failed_fixes records", len(failed))
    kv("proven_fixes records", len(proven))
    kv("tdd_eval_queue records", len(tdd_queue))

    escalation_reasons(ledger)
    tdd_evaluated_outcomes(ledger)
    category_status_matrix(ledger)
    time_series(ledger)
    escalation_closure(ledger, tdd_queue)
    repeated_failures(ledger, failed)
    failed_constraints(failed)
    proven_patterns_detail(proven)

    header("SUMMARY")
    print("  All reads completed. No writes were performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
