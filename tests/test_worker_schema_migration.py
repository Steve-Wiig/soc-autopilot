import json
import sqlite3

from engine.queue_priority import severity_to_priority
from engine.slm_triage_worker import (
    _ensure_claim_index,
    _ensure_priority_column,
)


def make_legacy_db():
    conn = sqlite3.connect(":memory:")

    conn.execute("""
        CREATE TABLE triage_queue (
            id TEXT PRIMARY KEY,
            severity INTEGER NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0
        )
    """)

    conn.executemany(
        """
        INSERT INTO triage_queue (
            id,
            severity,
            payload,
            status,
            created_at,
            attempts
        )
        VALUES (?, ?, ?, 'pending', ?, 0)
        """,
        [
            (
                f"job-{severity}",
                severity,
                json.dumps({"severity": severity}),
                f"2026-09-06T00:00:0{severity}+00:00",
            )
            for severity in range(6)
        ],
    )

    conn.commit()
    return conn


def columns(conn):
    return [
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(triage_queue)"
        )
    ]


def test_first_start_migrates_complete_worker_contract():
    conn = make_legacy_db()

    changed = _ensure_priority_column(conn)
    _ensure_claim_index(conn, changed)
    conn.commit()

    assert changed is True

    expected = [
        "id",
        "severity",
        "payload",
        "status",
        "created_at",
        "attempts",
        "priority",
        "started_at",
        "lease_expires_at",
        "last_heartbeat_at",
        "payload_ref",
        "failure_reason",
    ]

    assert columns(conn) == expected

    rows = conn.execute("""
        SELECT
            severity,
            priority,
            payload,
            payload_ref
        FROM triage_queue
        ORDER BY severity
    """).fetchall()

    assert len(rows) == 6

    for severity, priority, payload, payload_ref in rows:
        assert priority == severity_to_priority(severity)
        assert payload == payload_ref

    verdicts = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'verdicts'
    """).fetchall()

    assert verdicts == [("verdicts",)]

    indexes = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'index'
          AND name = 'idx_triage_claim'
    """).fetchall()

    assert indexes == [("idx_triage_claim",)]

    conn.close()


def test_second_start_is_idempotent():
    conn = make_legacy_db()

    changed_first = _ensure_priority_column(conn)
    _ensure_claim_index(conn, changed_first)
    conn.commit()

    before = {
        "columns": columns(conn),
        "rows": conn.execute("""
            SELECT
                id,
                severity,
                payload,
                status,
                created_at,
                attempts,
                priority,
                started_at,
                lease_expires_at,
                last_heartbeat_at,
                payload_ref,
                failure_reason
            FROM triage_queue
            ORDER BY id
        """).fetchall(),
        "indexes": conn.execute("""
            SELECT name, sql
            FROM sqlite_master
            WHERE type = 'index'
              AND tbl_name = 'triage_queue'
            ORDER BY name
        """).fetchall(),
    }

    changed_second = _ensure_priority_column(conn)
    _ensure_claim_index(conn, changed_second)
    conn.commit()

    after = {
        "columns": columns(conn),
        "rows": conn.execute("""
            SELECT
                id,
                severity,
                payload,
                status,
                created_at,
                attempts,
                priority,
                started_at,
                lease_expires_at,
                last_heartbeat_at,
                payload_ref,
                failure_reason
            FROM triage_queue
            ORDER BY id
        """).fetchall(),
        "indexes": conn.execute("""
            SELECT name, sql
            FROM sqlite_master
            WHERE type = 'index'
              AND tbl_name = 'triage_queue'
            ORDER BY name
        """).fetchall(),
    }

    assert changed_first is True
    assert changed_second is False
    assert before == after

    verdicts = conn.execute("""
        SELECT COUNT(*)
        FROM verdicts
    """).fetchone()[0]

    assert verdicts == 0

    conn.close()


def test_partial_priority_only_migration_is_repaired():
    conn = make_legacy_db()

    conn.execute(
        "ALTER TABLE triage_queue "
        "ADD COLUMN priority INTEGER NOT NULL DEFAULT 5"
    )
    conn.commit()

    changed = _ensure_priority_column(conn)
    _ensure_claim_index(conn, changed)
    conn.commit()

    assert changed is True

    required = {
        "priority",
        "started_at",
        "lease_expires_at",
        "last_heartbeat_at",
        "payload_ref",
        "failure_reason",
    }

    assert required.issubset(set(columns(conn)))

    row = conn.execute("""
        SELECT
            severity,
            priority,
            payload,
            payload_ref
        FROM triage_queue
        WHERE severity = 5
    """).fetchone()

    assert row is not None

    severity, priority, payload, payload_ref = row

    assert severity == 5
    assert priority == 1
    assert priority == severity_to_priority(severity)
    assert payload == payload_ref

    conn.close()


def test_verdicts_table_is_created_idempotently():
    conn = make_legacy_db()

    _ensure_priority_column(conn)
    _ensure_priority_column(conn)
    conn.commit()

    conn.execute("""
        INSERT INTO verdicts (
            job_id,
            result,
            processed_at
        )
        VALUES (?, ?, ?)
    """, (
        "job-5",
        json.dumps({"decision": "allow"}),
        "2026-09-06T00:00:00+00:00",
    ))

    conn.commit()

    row = conn.execute("""
        SELECT job_id, result, processed_at
        FROM verdicts
    """).fetchone()

    assert row is not None
    assert row[0] == "job-5"
    assert json.loads(row[1]) == {"decision": "allow"}
    assert row[2] == "2026-09-06T00:00:00+00:00"

    conn.close()
