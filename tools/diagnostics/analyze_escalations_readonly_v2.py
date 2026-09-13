#!/usr/bin/env python3
"""
Read-only diagnostic phase 2: schema, samples, source attribution.

SAFETY DISCIPLINE (identical to phase 1)
========================================
  * Path.read_text() only; open(..., 'r') only.
  * SQLite via URI mode=ro + PRAGMA query_only.
  * No write_text, no mkdir, no touch, no unlink, no rename, no replace.
  * No INSERT/UPDATE/DELETE/ATTACH/CREATE/DROP/VACUUM.
  * No subprocess. No network. No os.environ mutation.
  * Output is stdout only.

INTENT
======
Establish, from raw artifacts only:
  1. Schema of improvement_ledger.jsonl and other JSONL ledgers.
  2. What a TDD_EVALUATED record looks like (the largest bucket).
  3. What an ESCALATED record looks like (the actionable bucket).
  4. What the 4 fix_backlog.json entries actually are.
  5. What is inside queue.db.
  6. Where "14 proven patterns" and "Backlog: 0" are computed in source.

Run:
    python3 tools/analyze_escalations_readonly_v2.py
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any


if __name__ != "__main__":
    raise RuntimeError("diagnostic script; run as main, do not import")


REPO_ROOT = Path(__file__).resolve().parent.parent
OVERNIGHT = REPO_ROOT / "overnight"

TARGETS_JSONL = [
    OVERNIGHT / "improvement_ledger.jsonl",
    OVERNIGHT / "failed_fixes.jsonl",
    OVERNIGHT / "proven_fixes.jsonl",
    OVERNIGHT / "defeat_ledger.jsonl",
    OVERNIGHT / "tdd_eval_queue.jsonl",
    OVERNIGHT / "pi_reviewed.jsonl",
    OVERNIGHT / "pi_patches.archived.jsonl",
]

TARGETS_JSON = [
    OVERNIGHT / "improver_state.json",
    OVERNIGHT / "progress.json",
    OVERNIGHT / "lessons_learned.json",
    OVERNIGHT / "fix_backlog.json",
    OVERNIGHT / "api_usage.json",
    OVERNIGHT / "openrouter_quota.json",
    OVERNIGHT / "groq_model_cache.json",
    OVERNIGHT / "model_fallback_cache.json",
    OVERNIGHT / "morning_report.md",
]

TARGETS_DB = [
    OVERNIGHT / "queue.db",
]

SOURCE_GREP_PATTERNS = [
    (r"14", "proven patterns count"),
    (r"proven[_ ]?patterns", "proven patterns label"),
    (r"Backlog:\s*", "dashboard backlog label"),
    (r"fix_backlog", "backlog file reference"),
    (r"Success rate", "success rate label"),
    (r"TDD_EVALUATED", "TDD evaluated status"),
]

SOURCE_CANDIDATES = [
    REPO_ROOT / "tools" / "dashboard.py",
    REPO_ROOT / "overnight" / "report.py",
    REPO_ROOT / "overnight" / "dashboard.sh",
    REPO_ROOT / "overnight" / "self_improver.py",
    REPO_ROOT / "overnight" / "continuous_supervisor.sh",
]


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


def note(m: str) -> None:
    print(f"  [note] {m}")


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def read_text_safe(p: Path) -> str | None:
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def open_sqlite_ro(p: Path) -> sqlite3.Connection | None:
    if not p.is_file():
        return None
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        c.execute("PRAGMA query_only = ON")
        return c
    except sqlite3.Error:
        return None


# ---------------------------------------------------------------------------
# JSON / JSONL inspection
# ---------------------------------------------------------------------------
def schema_of_record(rec: Any) -> dict[str, str]:
    """Return {field: type_name} for a dict record."""
    if not isinstance(rec, dict):
        return {"<record>": type(rec).__name__}
    out: dict[str, str] = {}
    for k, v in rec.items():
        if isinstance(v, dict):
            out[k] = "dict(" + ",".join(sorted(v.keys())[:6]) + ")"
        elif isinstance(v, list):
            out[k] = f"list[{len(v)}]"
        elif v is None:
            out[k] = "None"
        else:
            out[k] = type(v).__name__
    return out


def inspect_jsonl(p: Path, max_sample: int = 3, top_n_status: int = 15) -> None:
    raw = read_text_safe(p)
    if raw is None:
        note(f"MISSING {p.relative_to(REPO_ROOT)}")
        return

    lines = [ln for ln in raw.splitlines() if ln.strip()]
    print(f"  file: {p.relative_to(REPO_ROOT)}")
    print(f"  size: {len(raw)} bytes, {len(lines)} non-blank lines")

    if not lines:
        return

    parsed: list[Any] = []
    parse_errors = 0
    for ln in lines:
        try:
            parsed.append(json.loads(ln))
        except json.JSONDecodeError:
            parse_errors += 1

    print(f"  parse_errors: {parse_errors}")
    if not parsed:
        return

    dict_records = [r for r in parsed if isinstance(r, dict)]
    print(f"  dict records: {len(dict_records)} / {len(parsed)}")

    # Schema from first N samples
    if dict_records:
        first = dict_records[0]
        print(f"  schema (first record): {schema_of_record(first)}")

    # Union of keys across all records (bounded by memory; 2233 recs fine)
    key_counts: Counter[str] = Counter()
    for r in dict_records:
        for k in r.keys():
            key_counts[k] += 1
    print(f"  key presence (n={len(dict_records)}):")
    for k, n in key_counts.most_common(20):
        print(f"    {k:<32} {n}")

    # Status distribution if present
    for status_field in ("status", "outcome", "decision"):
        vals = [r.get(status_field) for r in dict_records if status_field in r]
        if vals:
            counts = Counter(str(v) for v in vals)
            print(f"  {status_field} distribution ({len(vals)} records):")
            for v, n in counts.most_common(top_n_status):
                print(f"    {v:<24} {n}")

    # Category distribution if present
    for cat_field in ("category", "type", "kind"):
        vals = [r.get(cat_field) for r in dict_records if cat_field in r]
        if vals:
            counts = Counter(str(v) for v in vals)
            print(f"  {cat_field} distribution ({len(vals)} records):")
            for v, n in counts.most_common(top_n_status):
                print(f"    {v:<24} {n}")

    # Sample
    print(f"  sample (first {min(max_sample, len(dict_records))} records, truncated):")
    for i, r in enumerate(dict_records[:max_sample]):
        s = json.dumps(r, indent=None, sort_keys=True, default=str)
        if len(s) > 400:
            s = s[:400] + "...[truncated]"
        print(f"    [{i}] {s}")


def inspect_json(p: Path) -> None:
    raw = read_text_safe(p)
    if raw is None:
        note(f"MISSING {p.relative_to(REPO_ROOT)}")
        return

    print(f"  file: {p.relative_to(REPO_ROOT)}")
    print(f"  size: {len(raw)} bytes")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  NOT JSON: {e}")
        preview = raw.strip()[:200]
        print(f"  preview: {preview!r}")
        return

    if isinstance(data, list):
        print(f"  type: list of {len(data)}")
        if data and isinstance(data[0], dict):
            print(f"  schema (first item): {schema_of_record(data[0])}")
        for i, item in enumerate(data[:3]):
            s = json.dumps(item, default=str)
            if len(s) > 300:
                s = s[:300] + "...[truncated]"
            print(f"    [{i}] {s}")
    elif isinstance(data, dict):
        print(f"  type: dict, keys={list(data.keys())}")
        # Print small values
        for k, v in data.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                print(f"    {k} = {v!r}")
            elif isinstance(v, list):
                print(f"    {k} = list[{len(v)}]")
            elif isinstance(v, dict):
                print(f"    {k} = dict{list(v.keys())[:8]}")
    else:
        print(f"  type: {type(data).__name__}, value={data!r}")


# ---------------------------------------------------------------------------
# SQLite inspection
# ---------------------------------------------------------------------------
def inspect_db(p: Path) -> None:
    conn = open_sqlite_ro(p)
    if conn is None:
        note(f"MISSING or UNREADABLE {p.relative_to(REPO_ROOT)}")
        return

    print(f"  file: {p.relative_to(REPO_ROOT)}")
    try:
        size = p.stat().st_size
        print(f"  size: {size} bytes")
    except OSError:
        pass

    try:
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','index') ORDER BY type, name"
        ).fetchall()
    except sqlite3.Error as e:
        print(f"  cannot list schema: {e}")
        conn.close()
        return

    tables = [r[0] for r in rows if r[1] == "table"]
    indexes = [r[0] for r in rows if r[1] == "index"]
    print(f"  tables: {tables}")
    print(f"  indexes: {indexes}")

    for t in tables:
        try:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()]
            cnt_row = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()
            cnt = int(cnt_row[0]) if cnt_row else 0
        except sqlite3.Error:
            continue
        print(f"    table {t!r}: {cnt} rows, cols={cols}")

        # For each column that looks categorical, show top values
        for col in cols:
            if col.lower() in ("status", "state", "outcome", "decision", "kind", "type"):
                try:
                    vals = conn.execute(
                        f'SELECT "{col}", COUNT(*) FROM "{t}" GROUP BY "{col}" ORDER BY COUNT(*) DESC LIMIT 15'
                    ).fetchall()
                    print(f"      {col} distribution:")
                    for v, n in vals:
                        print(f"        {v!r:<24} {n}")
                except sqlite3.Error:
                    pass

    conn.close()


# ---------------------------------------------------------------------------
# Source attribution (pure-Python grep, no subprocess)
# ---------------------------------------------------------------------------
def search_source(pattern: str, label: str, paths: list[Path]) -> None:
    rx = re.compile(pattern)
    hits = 0
    for p in paths:
        raw = read_text_safe(p)
        if raw is None:
            continue
        for i, line in enumerate(raw.splitlines(), 1):
            if rx.search(line):
                hits += 1
                if hits <= 12:
                    stripped = line.strip()
                    if len(stripped) > 140:
                        stripped = stripped[:140] + "..."
                    print(f"    {p.relative_to(REPO_ROOT)}:{i}  {stripped}")
    if hits == 0:
        note(f"no hits for {label!r} in source candidates")
    elif hits > 12:
        print(f"    ... and {hits - 12} more hits")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print("soc-autopilot :: read-only escalation diagnostic phase 2")
    print(f"repo root: {REPO_ROOT}")

    header("A. improvement_ledger.jsonl — schema and samples")
    inspect_jsonl(OVERNIGHT / "improvement_ledger.jsonl", max_sample=5)

    header("B. fix_backlog.json — what are the 4 entries?")
    inspect_json(OVERNIGHT / "fix_backlog.json")

    header("C. failed_fixes.jsonl — what failed and why")
    inspect_jsonl(OVERNIGHT / "failed_fixes.jsonl", max_sample=3)

    header("D. proven_fixes.jsonl — where '14 proven patterns' might live")
    inspect_jsonl(OVERNIGHT / "proven_fixes.jsonl", max_sample=3)

    header("E. defeat_ledger.jsonl — adversarial defeats")
    inspect_jsonl(OVERNIGHT / "defeat_ledger.jsonl", max_sample=5)

    header("F. tdd_eval_queue.jsonl — TDD evaluation queue")
    inspect_jsonl(OVERNIGHT / "tdd_eval_queue.jsonl", max_sample=2)

    header("G. small JSON files")
    for p in TARGETS_JSON:
        sub(str(p.relative_to(REPO_ROOT)))
        inspect_json(p)

    header("H. SQLite probes")
    for p in TARGETS_DB:
        sub(str(p.relative_to(REPO_ROOT)))
        inspect_db(p)

    header("I. source attribution — where do dashboard numbers come from?")
    print("  candidates:")
    for p in SOURCE_CANDIDATES:
        present = "PRESENT" if p.is_file() else "MISSING"
        print(f"    {present}  {p.relative_to(REPO_ROOT)}")
    for pat, label in SOURCE_GREP_PATTERNS:
        print()
        print(f"  searching for: {label}  (pattern={pat!r})")
        search_source(pat, label, SOURCE_CANDIDATES)

    header("SUMMARY")
    print("  All reads completed. No writes were performed.")
    print("  Every file was opened in read mode; every SQLite connection used mode=ro.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
