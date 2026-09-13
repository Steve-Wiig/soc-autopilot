"""P1-1a: authoritative queue transition primitive.

Contract:
    read current DB state
        -> read DB-backed approval
        -> authorize_transition()
        -> UPDATE ... WHERE id = ? AND status = ?
        -> require rowcount == 1
"""
import sqlite3

import pytest

from engine.queue_manager import TriageQueueManager
from engine.strict_queue_transitions import (
    StateTransitionViolation,
    transition_queue_state,
)


def _setup():
    mgr = TriageQueueManager(db_path=":memory:")
    conn = mgr.conn
    conn.row_factory = sqlite3.Row
    # _init_schema writes fail_reason; ensure failure_reason exists too.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(triage_queue)").fetchall()}
    if "failure_reason" not in cols:
        conn.execute("ALTER TABLE triage_queue ADD COLUMN failure_reason TEXT")
        conn.commit()
    return conn


def _insert(conn, severity="low", status="processing"):
    cur = conn.execute(
        "INSERT INTO triage_queue (severity, payload_ref, status) VALUES (?, ?, ?)",
        (severity, "x", status),
    )
    conn.commit()
    return cur.lastrowid


def test_unknown_job_fails_closed():
    conn = _setup()
    with pytest.raises(StateTransitionViolation):
        transition_queue_state(conn, 9999, "completed")


def test_processing_to_completed_succeeds():
    conn = _setup()
    jid = _insert(conn, severity="low", status="processing")
    transition_queue_state(conn, jid, "completed")
    conn.commit()
    row = conn.execute("SELECT status FROM triage_queue WHERE id=?", (jid,)).fetchone()
    assert row["status"] == "completed"


def test_pending_to_completed_rejected():
    conn = _setup()
    jid = _insert(conn, severity="low", status="pending")
    with pytest.raises(StateTransitionViolation):
        transition_queue_state(conn, jid, "completed")


def test_terminal_state_cannot_transition_again():
    conn = _setup()
    jid = _insert(conn, severity="low", status="processing")
    transition_queue_state(conn, jid, "completed")
    conn.commit()
    with pytest.raises(StateTransitionViolation):
        transition_queue_state(conn, jid, "completed")


def test_critical_without_approval_fails_closed():
    conn = _setup()
    jid = _insert(conn, severity="critical", status="processing")
    with pytest.raises(StateTransitionViolation):
        transition_queue_state(conn, jid, "completed")


def test_critical_with_approval_succeeds():
    conn = _setup()
    jid = _insert(conn, severity="critical", status="processing")
    conn.execute(
        "INSERT INTO triage_queue_approvals (job_id, target_status, approved_by) "
        "VALUES (?, 'completed', 'tester')",
        (jid,),
    )
    conn.commit()
    transition_queue_state(conn, jid, "completed")
    conn.commit()
    row = conn.execute("SELECT status FROM triage_queue WHERE id=?", (jid,)).fetchone()
    assert row["status"] == "completed"


def test_failed_writes_failure_reason():
    conn = _setup()
    jid = _insert(conn, severity="low", status="processing")
    transition_queue_state(conn, jid, "failed", "unit test reason")
    conn.commit()
    row = conn.execute(
        "SELECT status, failure_reason FROM triage_queue WHERE id=?", (jid,)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["failure_reason"] == "unit test reason"


def test_stale_state_fails_closed():
    conn = _setup()
    jid = _insert(conn, severity="low", status="processing")
    # Competing writer advances the row first
    conn.execute("UPDATE triage_queue SET status='completed' WHERE id=?", (jid,))
    conn.commit()
    with pytest.raises(StateTransitionViolation):
        transition_queue_state(conn, jid, "completed")


def test_unsupported_target_fails_closed():
    conn = _setup()
    jid = _insert(conn, severity="low", status="processing")
    with pytest.raises(StateTransitionViolation):
        transition_queue_state(conn, jid, "cancelled")


def test_terminal_to_pending_rejected():
    """Terminal states have no successors; the primitive must fail closed."""
    conn = _setup()
    jid = _insert(conn, severity="low", status="processing")
    transition_queue_state(conn, jid, "completed")
    conn.commit()
    with pytest.raises(StateTransitionViolation):
        transition_queue_state(conn, jid, "pending")


def test_processing_to_pending_succeeds():
    conn = _setup()
    jid = _insert(conn, severity="low", status="processing")
    transition_queue_state(conn, jid, "pending")
    conn.commit()
    row = conn.execute(
        "SELECT status, started_at, lease_expires_at, last_heartbeat_at "
        "FROM triage_queue WHERE id=?",
        (jid,),
    ).fetchone()
    assert row["status"] == "pending"
    assert row["started_at"] is None
    assert row["lease_expires_at"] is None
    assert row["last_heartbeat_at"] is None


def test_reap_resets_low_retry_to_pending():
    mgr = TriageQueueManager(db_path=":memory:")
    conn = mgr.conn
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(triage_queue)").fetchall()}
    if "failure_reason" not in cols:
        conn.execute("ALTER TABLE triage_queue ADD COLUMN failure_reason TEXT")
        conn.commit()
    jid = _insert(conn, severity="low", status="processing")
    conn.execute(
        "UPDATE triage_queue SET lease_expires_at = '2000-01-01 00:00:00', attempts = 0 "
        "WHERE id = ?",
        (jid,),
    )
    conn.commit()
    mgr.reap_stale_jobs()
    row = conn.execute("SELECT status FROM triage_queue WHERE id=?", (jid,)).fetchone()
    assert row["status"] == "pending"


def test_reap_fails_noncritical_after_max_attempts():
    mgr = TriageQueueManager(db_path=":memory:")
    conn = mgr.conn
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(triage_queue)").fetchall()}
    if "failure_reason" not in cols:
        conn.execute("ALTER TABLE triage_queue ADD COLUMN failure_reason TEXT")
        conn.commit()
    jid = _insert(conn, severity="low", status="processing")
    conn.execute(
        "UPDATE triage_queue SET lease_expires_at = '2000-01-01 00:00:00', attempts = 99 "
        "WHERE id = ?",
        (jid,),
    )
    conn.commit()
    mgr.reap_stale_jobs()
    row = conn.execute(
        "SELECT status, failure_reason FROM triage_queue WHERE id=?", (jid,)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["failure_reason"] == "lease_expired_max_attempts"


def test_reap_critical_without_approval_escalates_to_pending():
    mgr = TriageQueueManager(db_path=":memory:")
    conn = mgr.conn
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(triage_queue)").fetchall()}
    if "failure_reason" not in cols:
        conn.execute("ALTER TABLE triage_queue ADD COLUMN failure_reason TEXT")
        conn.commit()
    jid = _insert(conn, severity="critical", status="processing")
    conn.execute(
        "UPDATE triage_queue SET lease_expires_at = '2000-01-01 00:00:00', attempts = 99 "
        "WHERE id = ?",
        (jid,),
    )
    conn.commit()
    mgr.reap_stale_jobs()
    row = conn.execute(
        "SELECT status, failure_reason FROM triage_queue WHERE id=?", (jid,)
    ).fetchone()
    assert row["status"] == "pending"
    assert row["failure_reason"] == "critical_escalation_no_approval"


def test_reap_critical_with_approval_fails():
    mgr = TriageQueueManager(db_path=":memory:")
    conn = mgr.conn
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(triage_queue)").fetchall()}
    if "failure_reason" not in cols:
        conn.execute("ALTER TABLE triage_queue ADD COLUMN failure_reason TEXT")
        conn.commit()
    jid = _insert(conn, severity="critical", status="processing")
    conn.execute(
        "UPDATE triage_queue SET lease_expires_at = '2000-01-01 00:00:00', attempts = 99 "
        "WHERE id = ?",
        (jid,),
    )
    conn.execute(
        "INSERT INTO triage_queue_approvals (job_id, target_status, approved_by) "
        "VALUES (?, 'failed', 'tester')",
        (jid,),
    )
    conn.commit()
    mgr.reap_stale_jobs()
    row = conn.execute(
        "SELECT status, failure_reason FROM triage_queue WHERE id=?", (jid,)
    ).fetchone()
    assert row["status"] == "failed"
    assert row["failure_reason"] == "lease_expired_max_attempts"


def test_ensure_queue_schema_on_fresh_legacy_table_succeeds():
    """Fresh table lacking 'payload' column must not break migrations."""
    import sqlite3 as _sqlite3
    from engine.queue_manager import ensure_queue_schema

    conn = _sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE triage_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            severity TEXT NOT NULL,
            payload_ref TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fail_reason TEXT
        )
    """)
    conn.commit()
    ensure_queue_schema(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(triage_queue)").fetchall()}
    assert "failure_reason" in cols


def test_ensure_queue_schema_migrates_fail_reason_to_failure_reason():
    import sqlite3 as _sqlite3
    from engine.queue_manager import ensure_queue_schema

    conn = _sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE triage_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            severity TEXT NOT NULL,
            payload_ref TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fail_reason TEXT
        )
    """)
    conn.execute(
        "INSERT INTO triage_queue (severity, payload_ref, status, fail_reason) "
        "VALUES ('low', 'x', 'failed', 'legacy_reason')"
    )
    conn.commit()
    ensure_queue_schema(conn)
    row = conn.execute(
        "SELECT failure_reason FROM triage_queue WHERE payload_ref='x'"
    ).fetchone()
    assert row[0] == "legacy_reason"
