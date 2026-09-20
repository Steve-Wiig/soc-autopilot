#!/usr/bin/env python3
"""Deduplication system for deferred fixes. Uses SQLite to track unique issues."""
import sqlite3
import hashlib
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = Path(__file__).parent.parent / "overnight" / "deferred_fixes.db"

def get_fingerprint(issue: dict) -> str:
    key_data = {
        "file": issue.get("file"),
        "line_start": issue.get("issue", {}).get("line_start"),
        "line_end": issue.get("issue", {}).get("line_end"),
        "category": issue.get("issue", {}).get("category"),
    }
    return hashlib.sha256(json.dumps(key_data, sort_keys=True).encode()).hexdigest()

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS deferred_fixes (
        fingerprint TEXT PRIMARY KEY, file_path TEXT NOT NULL, line_start INTEGER,
        line_end INTEGER, category TEXT, severity TEXT, description TEXT,
        suggestion TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
        occurrence_count INTEGER DEFAULT 1, status TEXT DEFAULT 'deferred')""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file ON deferred_fixes(file_path)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_category ON deferred_fixes(category)")
    conn.commit()
    conn.close()

def is_duplicate(issue: dict) -> bool:
    fingerprint = get_fingerprint(issue)
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT fingerprint FROM deferred_fixes WHERE fingerprint = ?", (fingerprint,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def add_or_update(issue: dict) -> bool:
    fingerprint = get_fingerprint(issue)
    now = datetime.now().isoformat()
    issue_data = issue.get("issue", {})
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT fingerprint, occurrence_count FROM deferred_fixes WHERE fingerprint = ?", (fingerprint,))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("UPDATE deferred_fixes SET last_seen = ?, occurrence_count = occurrence_count + 1 WHERE fingerprint = ?", (now, fingerprint))
        is_new = False
    else:
        cursor.execute("""INSERT INTO deferred_fixes (fingerprint, file_path, line_start, line_end, category, severity, 
            description, suggestion, first_seen, last_seen, occurrence_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'deferred')""",
            (fingerprint, issue.get("file"), issue_data.get("line_start"), issue_data.get("line_end"),
             issue_data.get("category"), issue_data.get("severity"), issue_data.get("description"),
             issue_data.get("suggestion"), now, now))
        is_new = True
    conn.commit()
    conn.close()
    return is_new

def get_stats() -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM deferred_fixes")
    total_unique = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(occurrence_count) FROM deferred_fixes")
    total_occurrences = cursor.fetchone()[0] or 0
    cursor.execute("SELECT category, COUNT(*), SUM(occurrence_count) FROM deferred_fixes GROUP BY category ORDER BY COUNT(*) DESC")
    by_category = cursor.fetchall()
    conn.close()
    return {
        "total_unique_issues": total_unique, "total_occurrences": total_occurrences,
        "duplicates_prevented": total_occurrences - total_unique,
        "by_category": [{"category": cat, "unique": count, "total": occ} for cat, count, occ in by_category]
    }

def cleanup_existing_backlog():
    backlog_path = Path(__file__).parent.parent / "overnight" / "fix_backlog_deferred.json"
    if not backlog_path.exists(): return 0
    with open(backlog_path) as f: backlog = json.load(f)
    init_db()
    unique_issues, duplicates = [], 0
    for issue in backlog:
        if add_or_update(issue): unique_issues.append(issue)
        else: duplicates += 1
    with open(backlog_path, 'w') as f: json.dump(unique_issues, f, indent=2)
    return duplicates

if __name__ == "__main__":
    import sys
    init_db()
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        print("Migrating existing backlog...")
        print(f"Removed {cleanup_existing_backlog()} duplicate entries")
        print(json.dumps(get_stats(), indent=2))
    else:
        print(json.dumps(get_stats(), indent=2))
