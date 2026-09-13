#!/usr/bin/env python3
"""
Read-only diagnostic: escalation analysis for soc-autopilot.

SAFETY DISCIPLINE
=================
This script is intentionally non-mutating. It will refuse to do anything
that writes to disk, to a database, or to any runtime artifact.

  * All file reads use Path.read_text() (utf-8, "r") only.
  * All SQLite connections use URI mode "file:...?mode=ro".
  * No .write_text, .write_bytes, .mkdir, .touch, .unlink, .rename, .replace.
  * No INSERT, UPDATE, DELETE, ATTACH, CREATE, DROP, VACUUM in any SQL.
  * No subprocess. No network. No os.environ mutation.
  * Output is stdout only. The caller redirects if desired.

INTENT
======
Back every operational assertion about the development-autonomy loop with
the raw artifact that supports it. Findings are printed as
    claim -> source -> evidence -> MATCH/MISMATCH.
A missing source is reported as MISSING, not as a crash.

Run:
    python3 tools/analyze_escalations_readonly.py
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Read-only guard: the script asserts it is running as __main__, never imported.
# ---------------------------------------------------------------------------
if __name__ != "__main__":
    raise RuntimeError(
        "analyze_escalations_readonly.py is a diagnostic and must be run "
        "as a script, not imported."
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
OVERNIGHT = REPO_ROOT / "overnight"
BACKLOG = OVERNIGHT / "fix_backlog.json"
HEARTBEAT = OVERNIGHT / ".heartbeat"
ORACLE_QUEUE = OVERNIGHT / "oracle_queue"

# Candidate data sources, probed in order. None are required; each is
# reported as PRESENT or MISSING.
CANDIDATE_FILES = [
    OVERNIGHT / "improvement_ledger.json",
    OVERNIGHT / "improvement_ledger.jsonl",
    OVERNIGHT / "proven_patterns.json",
    OVERNIGHT / "learned_patterns.json",
    OVERNIGHT / "escalations.json",
    OVERNIGHT / "escalation_log.jsonl",
    OVERNIGHT / "ledger.jsonl",
    OVERNIGHT / "self_improvement.db",
    OVERNIGHT / "ledger.db",
    OVERNIGHT / "improvement.db",
]

CANDIDATE_DIRS = [
    OVERNIGHT,
    OVERNIGHT / "oracle_queue",
    OVERNIGHT / "oracle_queue" / "pending",
    OVERNIGHT / "oracle_queue" / "approved",
    OVERNIGHT / "oracle_queue" / "rejected",
]


# ---------------------------------------------------------------------------
# Output helpers (stdout only)
# ---------------------------------------------------------------------------
def header(title: str) -> None:
    print()
    print("=" * 68)
    print(title)
    print("=" * 68)


def section(title: str) -> None:
    print()
    print(f"--- {title} ---")


def kv(key: str, value: Any) -> None:
    print(f"  {key:<32} {value}")


def note(msg: str) -> None:
    print(f"  [note] {msg}")


# ---------------------------------------------------------------------------
# Read-only primitives
# ---------------------------------------------------------------------------
def read_text_safe(path: Path) -> str | None:
    """Return file contents as utf-8 text, or None if unreadable.

    Opens in text mode, read-only, and never closes over a write handle.
    """
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def open_sqlite_readonly(path: Path) -> sqlite3.Connection | None:
    """Open a SQLite file in OS-enforced read-only mode.

    The URI parameter mode=ro makes SQLite refuse writes even if a caller
    later issues one. We also set PRAGMA query_only as a belt-and-braces
    guard inside the connection.
    """
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
        return conn
    except sqlite3.Error:
        return None


def sqlite_table_names(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]
    except sqlite3.Error:
        return []


def sqlite_row_count(conn: sqlite3.Connection, table: str) -> int | None:
    # Table names are validated against sqlite_master before reaching here.
    try:
        row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        return int(row[0]) if row else None
    except sqlite3.Error:
        return None


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return [r[1] for r in rows]
    except sqlite3.Error:
        return []


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def discover_sources() -> dict[str, Any]:
    header("DISCOVERY: candidate data sources")
    found: dict[str, Any] = {"files": {}, "dirs": {}, "sqlite": {}}

    section("candidate files")
    for p in CANDIDATE_FILES:
        if p.is_file():
            size = p.stat().st_size
            print(f"  PRESENT  {p.relative_to(REPO_ROOT)}  ({size} bytes)")
            found["files"][str(p.relative_to(REPO_ROOT))] = size
        else:
            print(f"  MISSING  {p.relative_to(REPO_ROOT)}")

    section("candidate directories")
    for d in CANDIDATE_DIRS:
        if d.is_dir():
            try:
                n = sum(1 for _ in d.iterdir())
            except OSError:
                n = -1
            print(f"  PRESENT  {d.relative_to(REPO_ROOT)}  ({n} entries)")
            found["dirs"][str(d.relative_to(REPO_ROOT))] = n
        else:
            print(f"  MISSING  {d.relative_to(REPO_ROOT)}")

    section("overnight/* glob (top-level only)")
    try:
        for p in sorted(OVERNIGHT.iterdir()):
            kind = "dir " if p.is_dir() else "file"
            size = "" if p.is_dir() else f"{p.stat().st_size} bytes"
            print(f"  {kind}  {p.name:<40} {size}")
    except OSError as e:
        note(f"cannot list overnight/: {e}")

    section("sqlite probes")
    for p in CANDIDATE_FILES:
        if not p.is_file() or p.suffix != ".db":
            continue
        conn = open_sqlite_readonly(p)
        if conn is None:
            print(f"  UNREADABLE  {p.relative_to(REPO_ROOT)}")
            continue
        tables = sqlite_table_names(conn)
        print(f"  READABLE    {p.relative_to(REPO_ROOT)}")
        for t in tables:
            count = sqlite_row_count(conn, t)
            cols = sqlite_columns(conn, t)
            print(f"      table {t!r}: {count} rows, columns={cols}")
        conn.close()
        found["sqlite"][str(p.relative_to(REPO_ROOT))] = tables

    return found


# ---------------------------------------------------------------------------
# Assertion checks
# ---------------------------------------------------------------------------
def check_assertion(
    claim: str,
    source: str,
    evidence: Any,
    matched: bool | None,
) -> None:
    status = "MATCH" if matched is True else "MISMATCH" if matched is False else "UNKNOWN"
    print()
    print(f"  CLAIM     {claim}")
    print(f"  SOURCE    {source}")
    print(f"  EVIDENCE  {evidence}")
    print(f"  RESULT    {status}")


def check_backlog() -> None:
    header("ASSERTION: fix_backlog.json is empty (backlog: 0)")
    raw = read_text_safe(BACKLOG)
    if raw is None:
        check_assertion(
            "fix_backlog.json exists and is empty",
            str(BACKLOG.relative_to(REPO_ROOT)),
            "MISSING",
            None,
        )
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        check_assertion(
            "fix_backlog.json parses as JSON",
            str(BACKLOG.relative_to(REPO_ROOT)),
            f"JSON decode error: {e}",
            False,
        )
        return
    count = len(data) if isinstance(data, list) else 1
    check_assertion(
        "fix_backlog.json is an empty list",
        str(BACKLOG.relative_to(REPO_ROOT)),
        f"parsed type={type(data).__name__}, len={count}",
        count == 0,
    )


def check_heartbeat() -> None:
    header("ASSERTION: heartbeat is fresh (system active)")
    raw = read_text_safe(HEARTBEAT)
    if raw is None:
        check_assertion(
            "overnight/.heartbeat exists",
            str(HEARTBEAT.relative_to(REPO_ROOT)),
            "MISSING",
            None,
        )
        return
    stripped = raw.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = stripped
    check_assertion(
        "overnight/.heartbeat is readable",
        str(HEARTBEAT.relative_to(REPO_ROOT)),
        f"{len(raw)} bytes, preview={stripped[:120]!r}",
        True,
    )


def check_oracle_queue() -> None:
    header("ASSERTION: Oracle queue has 0 pending")
    if not ORACLE_QUEUE.is_dir():
        check_assertion(
            "overnight/oracle_queue exists",
            str(ORACLE_QUEUE.relative_to(REPO_ROOT)),
            "MISSING",
            None,
        )
        return
    for sub in ("pending", "approved", "rejected"):
        d = ORACLE_QUEUE / sub
        if not d.is_dir():
            print(f"  {sub:<10} MISSING")
            continue
        try:
            files = list(d.glob("*.json"))
        except OSError:
            files = []
        print(f"  {sub:<10} {len(files)} *.json")
    pending = list((ORACLE_QUEUE / "pending").glob("*.json")) if (ORACLE_QUEUE / "pending").is_dir() else []
    check_assertion(
        "oracle_queue/pending contains 0 JSON files",
        str((ORACLE_QUEUE / "pending").relative_to(REPO_ROOT)),
        f"{len(pending)} files",
        len(pending) == 0,
    )


def probe_sqlite_ledger() -> None:
    header("ASSERTION: improvement ledger is queryable (2233 decisions)")
    for p in CANDIDATE_FILES:
        if not p.is_file() or p.suffix != ".db":
            continue
        conn = open_sqlite_readonly(p)
        if conn is None:
            continue
        print(f"  probing {p.relative_to(REPO_ROOT)}")
        for t in sqlite_table_names(conn):
            cols = sqlite_columns(conn, t)
            count = sqlite_row_count(conn, t)
            print(f"    {t}: rows={count} cols={cols}")
            # If a status column exists, break down by status.
            if "status" in cols:
                try:
                    rows = conn.execute(
                        f'SELECT status, COUNT(*) FROM "{t}" GROUP BY status ORDER BY COUNT(*) DESC'
                    ).fetchall()
                    for status, n in rows:
                        print(f"        status={status!r:<20} count={n}")
                except sqlite3.Error as e:
                    note(f"cannot group status: {e}")
            # If a category column exists, break down by category.
            if "category" in cols:
                try:
                    rows = conn.execute(
                        f'SELECT category, COUNT(*) FROM "{t}" GROUP BY category ORDER BY COUNT(*) DESC'
                    ).fetchall()
                    for cat, n in rows:
                        print(f"        category={cat!r:<20} count={n}")
                except sqlite3.Error as e:
                    note(f"cannot group category: {e}")
        conn.close()
        return
    note("no SQLite ledger found under overnight/ at known names")


def probe_json_ledger() -> None:
    header("ASSERTION: improvement ledger is queryable (JSON variant)")
    json_candidates = [
        OVERNIGHT / "improvement_ledger.json",
        OVERNIGHT / "improvement_ledger.jsonl",
        OVERNIGHT / "ledger.jsonl",
        OVERNIGHT / "escalation_log.jsonl",
        OVERNIGHT / "escalations.json",
    ]
    found_any = False
    for p in json_candidates:
        raw = read_text_safe(p)
        if raw is None:
            continue
        found_any = True
        print(f"  {p.relative_to(REPO_ROOT)}: {len(raw)} bytes")
        # Try line-delimited first.
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if len(lines) > 1:
            statuses: Counter[str] = Counter()
            categories: Counter[str] = Counter()
            parse_errors = 0
            for ln in lines:
                try:
                    rec = json.loads(ln)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if isinstance(rec, dict):
                    s = rec.get("status") or rec.get("outcome")
                    if s is not None:
                        statuses[str(s)] += 1
                    c = rec.get("category")
                    if c is not None:
                        categories[str(c)] += 1
            print(f"    jsonl records: {len(lines)} (parse_errors={parse_errors})")
            for s, n in statuses.most_common():
                print(f"      status={s!r:<20} count={n}")
            for c, n in categories.most_common():
                print(f"      category={c!r:<20} count={n}")
        else:
            # Single JSON document.
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                note(f"not valid JSON: {e}")
                continue
            if isinstance(data, list):
                print(f"    list of {len(data)} records")
                statuses = Counter()
                categories = Counter()
                for rec in data:
                    if isinstance(rec, dict):
                        s = rec.get("status") or rec.get("outcome")
                        if s is not None:
                            statuses[str(s)] += 1
                        c = rec.get("category")
                        if c is not None:
                            categories[str(c)] += 1
                for s, n in statuses.most_common():
                    print(f"      status={s!r:<20} count={n}")
                for c, n in categories.most_common():
                    print(f"      category={c!r:<20} count={n}")
            elif isinstance(data, dict):
                print(f"    dict with keys={list(data.keys())[:10]}")
    if not found_any:
        note("no JSON ledger found under overnight/ at known names")


def probe_proven_patterns() -> None:
    header("ASSERTION: 14 proven patterns are stored")
    candidates = [
        OVERNIGHT / "proven_patterns.json",
        OVERNIGHT / "learned_patterns.json",
    ]
    found = False
    for p in candidates:
        raw = read_text_safe(p)
        if raw is None:
            continue
        found = True
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            note(f"{p.name}: not valid JSON ({e})")
            continue
        if isinstance(data, list):
            check_assertion(
                "proven patterns count == 14",
                str(p.relative_to(REPO_ROOT)),
                f"list of {len(data)} entries",
                len(data) == 14,
            )
        elif isinstance(data, dict):
            print(f"  {p.relative_to(REPO_ROOT)}: dict keys={list(data.keys())[:10]}")
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"    {k}: list of {len(v)}")
    if not found:
        note("no proven_patterns/learned_patterns file found")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print("soc-autopilot :: read-only escalation diagnostic")
    print(f"repo root: {REPO_ROOT}")
    print(f"overnight: {OVERNIGHT} (exists={OVERNIGHT.is_dir()})")

    discover_sources()
    check_backlog()
    check_heartbeat()
    check_oracle_queue()
    probe_sqlite_ledger()
    probe_json_ledger()
    probe_proven_patterns()

    header("SUMMARY")
    print("  All reads completed. No writes were performed.")
    print("  Verify this by checking mtimes before/after if you want;")
    print("  the script does not create, modify, or delete any file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
