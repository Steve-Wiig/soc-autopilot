from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "engine" / "slm_triage_worker.py"
QUEUE_MANAGER = ROOT / "engine" / "queue_manager.py"


def test_worker_uses_canonical_claim():
    source = WORKER.read_text()
    assert "queue_manager.claim_job(" in source
    assert "UPDATE triage_queue SET status = 'processing'" not in source


def test_worker_uses_canonical_stale_recovery():
    source = WORKER.read_text()
    assert "queue_manager.reap_stale_jobs()" in source
    assert "UPDATE triage_queue SET status = 'pending'" not in source


def test_worker_keeps_terminal_transition_authority():
    source = WORKER.read_text()
    assert "transition_queue_state(conn, job_id" in source


def test_production_passes_existing_queue_manager():
    source = WORKER.read_text()
    assert "reap_stale(conn, queue_manager)" in source


def test_schema_migration_has_last_modified_by():
    source = QUEUE_MANAGER.read_text()
    assert '"last_modified_by": "TEXT NOT NULL DEFAULT \'system\'"' in source


def test_schema_migration_has_approval_table():
    source = QUEUE_MANAGER.read_text()
    assert "CREATE TABLE IF NOT EXISTS triage_queue_approvals" in source


def test_schema_migration_creates_required_objects():
    from engine.queue_manager import ensure_queue_schema

    conn = sqlite3.connect(":memory:")

    conn.execute("""
        CREATE TABLE triage_queue (
            id INTEGER PRIMARY KEY,
            severity TEXT,
            payload_ref TEXT,
            status TEXT,
            created_at TEXT,
            attempts INTEGER DEFAULT 0
        )
    """)

    ensure_queue_schema(conn)

    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(triage_queue)"
        ).fetchall()
    }

    assert "last_modified_by" in columns

    table = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name='triage_queue_approvals'
    """).fetchone()

    assert table == ("triage_queue_approvals",)

    conn.close()


def test_heartbeat_does_not_touch_pending_jobs():
    import sqlite3
    from engine.slm_triage_worker import heartbeat

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE triage_queue (
            id INTEGER PRIMARY KEY,
            status TEXT,
            last_heartbeat_at TEXT,
            lease_expires_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO triage_queue (id, status) VALUES (1, 'pending')"
    )
    conn.commit()

    heartbeat(conn, 1, 300)

    row = conn.execute("""
        SELECT last_heartbeat_at, lease_expires_at
        FROM triage_queue
        WHERE id = 1
    """).fetchone()

    assert row == (None, None)
    conn.close()


def test_lease_heartbeat_during_inference_lifecycle(monkeypatch):
    import time
    from engine import slm_triage_worker

    calls = []

    class FakeQueueManager:
        def __init__(self, db_path, lease_interval, max_attempts):
            calls.append(
                ("init", db_path, lease_interval, max_attempts)
            )

        def heartbeat(self, job_id):
            calls.append(("heartbeat", job_id))

    monkeypatch.setattr(
        slm_triage_worker,
        "TriageQueueManager",
        FakeQueueManager,
    )

    stop_event, thread, failures = (
        slm_triage_worker._start_lease_heartbeat(
            "test-db",
            42,
            3,
        )
    )

    time.sleep(1.1)

    stop_event.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert failures == []
    assert calls
    assert calls[0] == ("init", "test-db", 3, 3)
    assert ("heartbeat", 42) in calls



def test_heartbeat_fails_closed_on_zero_row_update():
    import sqlite3
    from engine.queue_manager import (
        LeaseLostError,
        TriageQueueManager,
    )

    conn = sqlite3.connect(":memory:")

    manager = TriageQueueManager.__new__(TriageQueueManager)
    manager.conn = conn
    manager.cursor = conn.cursor()
    manager.lease_interval = 300
    manager._lease_modifier = "+5 minutes"

    conn.execute("""
        CREATE TABLE triage_queue (
            id INTEGER PRIMARY KEY,
            status TEXT,
            last_heartbeat_at TEXT,
            lease_expires_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO triage_queue (id, status) VALUES (1, 'pending')"
    )
    conn.commit()

    try:
        manager.heartbeat(1)
    except LeaseLostError as exc:
        assert "Lease lost for job 1" in str(exc)
    else:
        raise AssertionError(
            "heartbeat must fail closed when zero rows are updated"
        )

    row = conn.execute("""
        SELECT last_heartbeat_at, lease_expires_at
        FROM triage_queue
        WHERE id = 1
    """).fetchone()

    assert row == (None, None)
    conn.close()


def test_heartbeat_succeeds_for_owned_processing_job():
    import sqlite3
    from engine.queue_manager import TriageQueueManager

    conn = sqlite3.connect(":memory:")

    manager = TriageQueueManager.__new__(TriageQueueManager)
    manager.conn = conn
    manager.cursor = conn.cursor()
    manager.lease_interval = 300
    manager._lease_modifier = "+5 minutes"

    conn.execute("""
        CREATE TABLE triage_queue (
            id INTEGER PRIMARY KEY,
            status TEXT,
            last_heartbeat_at TEXT,
            lease_expires_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO triage_queue (id, status) VALUES (1, 'processing')"
    )
    conn.commit()

    manager.heartbeat(1)

    row = conn.execute("""
        SELECT last_heartbeat_at, lease_expires_at
        FROM triage_queue
        WHERE id = 1
    """).fetchone()

    assert row[0] is not None
    assert row[1] is not None
    conn.close()



def test_reaper_transition_rejects_renewed_lease():
    import sqlite3
    from engine.strict_queue_transitions import (
        StateTransitionViolation,
        transition_queue_state,
    )

    conn = sqlite3.connect(":memory:")

    conn.execute("""
        CREATE TABLE triage_queue (
            id INTEGER PRIMARY KEY,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            lease_expires_at TEXT,
            started_at TEXT,
            last_heartbeat_at TEXT,
            failure_reason TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE triage_queue_approvals (
            job_id INTEGER,
            target_status TEXT
        )
    """)

    observed_stale_lease = "2020-01-01 00:00:00"
    renewed_lease = "2099-01-01 00:00:00"

    conn.execute(
        """
        INSERT INTO triage_queue
            (id, severity, status, lease_expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (1, "low", "processing", renewed_lease),
    )
    conn.commit()

    try:
        transition_queue_state(
            conn,
            1,
            "pending",
            expected_lease_expires_at=observed_stale_lease,
        )
    except StateTransitionViolation as exc:
        assert "Lease changed before transition" in str(exc)
    else:
        raise AssertionError(
            "reaper must reject a job whose lease changed after stale selection"
        )

    status = conn.execute(
        "SELECT status, lease_expires_at FROM triage_queue WHERE id = 1"
    ).fetchone()

    assert status == ("processing", renewed_lease)
    conn.close()


def test_reaper_transition_accepts_unchanged_expired_lease():
    import sqlite3
    from engine.strict_queue_transitions import transition_queue_state

    conn = sqlite3.connect(":memory:")

    conn.execute("""
        CREATE TABLE triage_queue (
            id INTEGER PRIMARY KEY,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            lease_expires_at TEXT,
            started_at TEXT,
            last_heartbeat_at TEXT,
            failure_reason TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE triage_queue_approvals (
            job_id INTEGER,
            target_status TEXT
        )
    """)

    stale_lease = "2020-01-01 00:00:00"

    conn.execute(
        """
        INSERT INTO triage_queue
            (id, severity, status, lease_expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (1, "low", "processing", stale_lease),
    )
    conn.commit()

    transition_queue_state(
        conn,
        1,
        "pending",
        expected_lease_expires_at=stale_lease,
    )
    conn.commit()

    status = conn.execute(
        "SELECT status, lease_expires_at FROM triage_queue WHERE id = 1"
    ).fetchone()

    assert status == ("pending", None)
    conn.close()

