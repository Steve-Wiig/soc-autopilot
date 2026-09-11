import sqlite3

import pytest

from engine.queue_manager import TriageQueueManager


def make_mgr():
    mgr = TriageQueueManager.__new__(TriageQueueManager)
    mgr.conn = sqlite3.connect(":memory:")
    mgr.conn.execute("PRAGMA foreign_keys = ON")
    mgr.cursor = mgr.conn.cursor()
    mgr._init_schema()
    return mgr


def insert_job(mgr, job_id, severity, payload_ref=None, status="processing"):
    mgr.cursor.execute(
        """
        INSERT INTO triage_queue
            (id, severity, payload_ref, status)
        VALUES (?, ?, ?, ?)
        """,
        (
            job_id,
            severity,
            payload_ref or f"test-payload-{job_id}",
            status,
        ),
    )
    mgr.conn.commit()


def test_critical_job_requires_approval():
    """Critical jobs cannot complete without a DB approval."""
    mgr = make_mgr()
    insert_job(mgr, 1, "critical")

    with pytest.raises(
        RuntimeError,
        match=r"Critical job 1 requires approval to transition to completed",
    ):
        mgr.require_approval(1, "completed")


def test_critical_job_with_approval_passes():
    """A matching DB approval permits the requested transition."""
    mgr = make_mgr()
    insert_job(mgr, 2, "critical")

    mgr.approve_job(
        2,
        "completed",
        "human",
        reason="Reviewed by analyst",
        judge_metadata='{"source":"test"}',
    )

    mgr.require_approval(2, "completed")


def test_critical_job_approval_is_target_specific():
    """Approval for completed must not authorize failed, and vice versa."""
    mgr = make_mgr()
    insert_job(mgr, 3, "critical")

    mgr.approve_job(3, "completed", "human")

    mgr.require_approval(3, "completed")

    with pytest.raises(
        RuntimeError,
        match=r"requires approval to transition to failed",
    ):
        mgr.require_approval(3, "failed")


def test_noncritical_job_passes_without_approval():
    """Non-critical jobs do not require explicit approval."""
    mgr = make_mgr()
    insert_job(mgr, 4, "high")

    mgr.require_approval(4, "completed")
    mgr.require_approval(4, "failed")


def test_legacy_enforce_approval_wrapper_uses_db_gate():
    """Compatibility wrapper must delegate to the DB-backed gate."""
    mgr = make_mgr()
    insert_job(mgr, 5, "critical")

    with pytest.raises(
        RuntimeError,
        match=r"requires approval to transition to completed",
    ):
        mgr._enforce_approval(5)


def test_worker_cannot_forge_db_approval():
    """A worker-side approval payload cannot bypass the DB approval table."""
    mgr = make_mgr()
    insert_job(mgr, 6, "critical")

    # There is intentionally no row in triage_queue_approvals.
    # A worker payload is irrelevant because the gate queries the database.
    with pytest.raises(
        RuntimeError,
        match=r"requires approval to transition to completed",
    ):
        mgr._enforce_approval(6)


def test_missing_approval_table_fails_closed():
    """A missing approval table must fail rather than silently allow completion."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE triage_queue (
            id INTEGER PRIMARY KEY,
            severity TEXT NOT NULL,
            payload_ref TEXT NOT NULL,
            status TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO triage_queue
            (id, severity, payload_ref, status)
        VALUES (1, 'critical', 'test-payload-1', 'processing')
        """
    )
    conn.commit()

    mgr = TriageQueueManager.__new__(TriageQueueManager)
    mgr.conn = conn
    mgr.cursor = conn.cursor()

    with pytest.raises(sqlite3.OperationalError, match="triage_queue_approvals"):
        mgr.require_approval(1, "completed")


def test_approve_job_records_provenance():
    """Approval provenance fields are persisted with the approval."""
    mgr = make_mgr()
    insert_job(mgr, 7, "critical")

    mgr.approve_job(
        7,
        "completed",
        "human",
        reason="Verified during test",
        judge_metadata='{"model":"test-model","confidence":1.0}',
    )

    row = mgr.cursor.execute(
        """
        SELECT job_id, target_status, approved_by, reason, judge_metadata
        FROM triage_queue_approvals
        WHERE job_id = ? AND target_status = ?
        """,
        (7, "completed"),
    ).fetchone()

    assert row == (
        7,
        "completed",
        "human",
        "Verified during test",
        '{"model":"test-model","confidence":1.0}',
    )
