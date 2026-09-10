import json
import sqlite3

from engine.intake_wazuh import persist_alert
from engine.queue_priority import (
    DEFAULT_PRIORITY,
    NUMERIC_SEVERITY_PRIORITY,
    priority_case_sql,
    severity_to_priority,
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
    return conn


def make_migrated_db():
    conn = make_legacy_db()

    conn.execute(
        "ALTER TABLE triage_queue "
        "ADD COLUMN priority INTEGER NOT NULL DEFAULT 5"
    )
    conn.execute(
        "ALTER TABLE triage_queue "
        "ADD COLUMN started_at TEXT"
    )
    conn.execute(
        "ALTER TABLE triage_queue "
        "ADD COLUMN lease_expires_at TEXT"
    )
    conn.execute(
        "ALTER TABLE triage_queue "
        "ADD COLUMN last_heartbeat_at TEXT"
    )
    conn.execute(
        "ALTER TABLE triage_queue "
        "ADD COLUMN payload_ref TEXT"
    )
    conn.execute(
        "ALTER TABLE triage_queue "
        "ADD COLUMN failure_reason TEXT"
    )

    conn.commit()
    return conn


def test_numeric_priority_mapping():
    expected = {
        0: 5,
        1: 5,
        2: 4,
        3: 3,
        4: 2,
        5: 1,
    }

    assert NUMERIC_SEVERITY_PRIORITY == expected

    for severity, priority in expected.items():
        assert severity_to_priority(severity) == priority


def test_numeric_edge_values_match_worker_semantics():
    assert severity_to_priority(6) == 1
    assert severity_to_priority(99) == 1
    assert severity_to_priority(-1) == DEFAULT_PRIORITY
    assert severity_to_priority(4.9) == 2
    assert severity_to_priority(2.1) == 4
    assert severity_to_priority(True) == DEFAULT_PRIORITY


def test_named_severity_mapping():
    assert severity_to_priority("critical") == 1
    assert severity_to_priority(" HIGH ") == 2
    assert severity_to_priority("Medium") == 3
    assert severity_to_priority(" low ") == 4
    assert severity_to_priority("unknown") == DEFAULT_PRIORITY


def test_sql_priority_expression_matches_python_for_supported_values():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE t(severity)"
    )

    values = [
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        -1,
        4.9,
        "critical",
        "HIGH",
        " medium ",
        "low",
        "unknown",
    ]

    conn.executemany(
        "INSERT INTO t(severity) VALUES (?)",
        [(value,) for value in values],
    )

    expr = priority_case_sql("severity")

    rows = conn.execute(
        f"SELECT severity, {expr} AS priority FROM t"
    ).fetchall()

    for severity, priority in rows:
        assert priority == severity_to_priority(severity)

    conn.close()


def test_legacy_schema_producer_contract_is_preserved():
    conn = make_legacy_db()

    payload = {
        "id": "legacy-test",
        "severity": 5,
        "payload": {"agent": "legacy"},
        "timestamp": "2026-09-06T00:00:00+00:00",
    }

    persist_alert(conn, payload)

    row = conn.execute("""
        SELECT id, severity, payload, status, attempts
        FROM triage_queue
    """).fetchone()

    assert row == (
        "legacy-test",
        5,
        json.dumps({"agent": "legacy"}),
        "pending",
        0,
    )

    conn.close()


def test_migrated_schema_producer_populates_priority_and_payload_ref():
    conn = make_migrated_db()

    payload = {
        "id": "migrated-test",
        "severity": 5,
        "payload": {"agent": "migrated"},
        "timestamp": "2026-09-06T00:00:00+00:00",
    }

    persist_alert(conn, payload)

    row = conn.execute("""
        SELECT
            id,
            severity,
            payload,
            status,
            attempts,
            priority,
            payload_ref
        FROM triage_queue
    """).fetchone()

    expected_payload = json.dumps({"agent": "migrated"})

    assert row == (
        "migrated-test",
        5,
        expected_payload,
        "pending",
        0,
        1,
        expected_payload,
    )

    conn.close()


def test_migrated_schema_all_wazuh_levels_get_correct_priority():
    conn = make_migrated_db()

    for severity in range(6):
        payload = {
            "id": f"severity-{severity}",
            "severity": severity,
            "payload": {
                "agent": "corpus",
                "severity": severity,
            },
            "timestamp": f"2026-09-06T00:00:0{severity}+00:00",
        }

        persist_alert(conn, payload)

    rows = conn.execute("""
        SELECT severity, priority, payload, payload_ref
        FROM triage_queue
        ORDER BY severity
    """).fetchall()

    assert len(rows) == 6

    for severity, priority, payload, payload_ref in rows:
        assert priority == severity_to_priority(severity)
        assert payload == payload_ref

    conn.close()


def test_partial_migration_is_rejected():
    conn = make_legacy_db()
    conn.execute(
        "ALTER TABLE triage_queue "
        "ADD COLUMN priority INTEGER NOT NULL DEFAULT 5"
    )
    conn.commit()

    payload = {
        "id": "partial",
        "severity": 5,
        "payload": {"agent": "partial"},
        "timestamp": "2026-09-06T00:00:00+00:00",
    }

    try:
        persist_alert(conn, payload)
    except RuntimeError as exc:
        assert "partial triage_queue migration" in str(exc)
    else:
        raise AssertionError(
            "partial schema was accepted unexpectedly"
        )

    conn.close()
