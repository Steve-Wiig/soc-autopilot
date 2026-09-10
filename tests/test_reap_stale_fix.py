import sqlite3
from datetime import datetime, timedelta, timezone

from engine.slm_triage_worker import (
    _ensure_claim_index,
    _ensure_priority_column,
    heartbeat,
    reap_stale,
)


def make_db(tmp_path):
    db = tmp_path / "reap.db"

    conn = sqlite3.connect(db)

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

    conn.executemany("""
        INSERT INTO triage_queue
        (
            id,
            severity,
            payload,
            status,
            created_at,
            attempts
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, [
        (
            "job-future",
            5,
            '{"agent":"future"}',
            "processing",
            "2026-09-06 15:00:00",
            1,
        ),
        (
            "job-expired",
            5,
            '{"agent":"expired"}',
            "processing",
            "2026-09-06 15:00:00",
            1,
        ),
        (
            "job-pending",
            5,
            '{"agent":"pending"}',
            "pending",
            "2026-09-06 15:00:00",
            0,
        ),
    ])

    conn.commit()

    _ensure_priority_column(conn)
    _ensure_claim_index(conn, True)

    now = datetime.now(timezone.utc)

    future = (
        now + timedelta(minutes=5)
    ).strftime("%Y-%m-%d %H:%M:%S")

    expired = (
        now - timedelta(minutes=5)
    ).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        UPDATE triage_queue
        SET
            started_at=?,
            lease_expires_at=?,
            last_heartbeat_at=?
        WHERE id='job-future'
    """, (
        now.strftime("%Y-%m-%d %H:%M:%S"),
        future,
        now.strftime("%Y-%m-%d %H:%M:%S"),
    ))

    conn.execute("""
        UPDATE triage_queue
        SET
            started_at=?,
            lease_expires_at=?,
            last_heartbeat_at=?
        WHERE id='job-expired'
    """, (
        expired,
        expired,
        expired,
    ))

    conn.commit()

    return conn


def test_expired_job_is_reaped(tmp_path):
    conn = make_db(tmp_path)

    reap_stale(conn)

    row = conn.execute("""
        SELECT
            status,
            started_at,
            lease_expires_at,
            last_heartbeat_at
        FROM triage_queue
        WHERE id='job-expired'
    """).fetchone()

    assert row == (
        "pending",
        None,
        None,
        None,
    )

    conn.close()


def test_future_job_is_not_reaped(tmp_path):
    conn = make_db(tmp_path)

    reap_stale(conn)

    row = conn.execute("""
        SELECT
            status,
            started_at,
            lease_expires_at,
            last_heartbeat_at
        FROM triage_queue
        WHERE id='job-future'
    """).fetchone()

    assert row[0] == "processing"
    assert row[1] is not None
    assert row[2] is not None
    assert row[3] is not None

    conn.close()


def test_pending_job_is_not_modified(tmp_path):
    conn = make_db(tmp_path)

    before = conn.execute("""
        SELECT
            status,
            started_at,
            lease_expires_at,
            last_heartbeat_at,
            attempts
        FROM triage_queue
        WHERE id='job-pending'
    """).fetchone()

    reap_stale(conn)

    after = conn.execute("""
        SELECT
            status,
            started_at,
            lease_expires_at,
            last_heartbeat_at,
            attempts
        FROM triage_queue
        WHERE id='job-pending'
    """).fetchone()

    assert after == before

    conn.close()


def test_heartbeat_writes_same_timestamp_contract(tmp_path):
    conn = make_db(tmp_path)

    heartbeat(
        conn,
        "job-pending",
        300,
    )

    row = conn.execute("""
        SELECT
            last_heartbeat_at,
            lease_expires_at
        FROM triage_queue
        WHERE id='job-pending'
    """).fetchone()

    heartbeat_at, lease_at = row

    assert heartbeat_at is not None
    assert lease_at is not None

    assert len(heartbeat_at) == 19
    assert len(lease_at) == 19

    datetime.strptime(
        heartbeat_at,
        "%Y-%m-%d %H:%M:%S",
    )

    datetime.strptime(
        lease_at,
        "%Y-%m-%d %H:%M:%S",
    )

    conn.close()


def test_iso_lease_is_not_silently_reclaimed_by_legacy_compare(tmp_path):
    """
    Documentation test for the timestamp contract.

    The worker now owns the canonical second-resolution UTC string
    representation. ISO-8601 strings with T/+00:00 are intentionally
    outside that storage contract.
    """

    conn = make_db(tmp_path)

    iso_expired = (
        datetime.now(timezone.utc)
        - timedelta(minutes=5)
    ).isoformat()

    conn.execute("""
        UPDATE triage_queue
        SET
            status='processing',
            lease_expires_at=?
        WHERE id='job-expired'
    """, (iso_expired,))

    conn.commit()

    reap_stale(conn)

    row = conn.execute("""
        SELECT status
        FROM triage_queue
        WHERE id='job-expired'
    """).fetchone()

    assert row == ("processing",)

    conn.close()
