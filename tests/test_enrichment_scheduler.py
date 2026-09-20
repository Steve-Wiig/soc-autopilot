"""Tests for engine/enrichment_scheduler.py.
Uses real in-memory SQLite with correct schema (remaining column).
"""
import sys
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.enrichment_scheduler import update_quota, get_db_connections


def _make_quota_db():
    """Create real in-memory SQLite with the ACTUAL schema used by the implementation."""
    conn = sqlite3.connect(":memory:")
    # The implementation uses: SELECT remaining FROM quota_ledger
    # and: UPDATE quota_ledger SET remaining = remaining - ?
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quota_ledger (
            provider TEXT PRIMARY KEY,
            remaining INTEGER DEFAULT 100
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quota_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            cost INTEGER NOT NULL,
            remaining_before INTEGER NOT NULL,
            remaining_after INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            actor TEXT DEFAULT 'system',
            approval_ref TEXT
        )
    """)
    conn.execute("INSERT INTO quota_ledger (provider, remaining) VALUES ('gemini', 90)")
    conn.commit()
    return conn


def test_update_quota_increments_used():
    """update_quota should decrement the remaining counter."""
    conn = _make_quota_db()
    update_quota(conn, "gemini", 5)
    # Verify via direct SQL (check_quota deprecated/removed)
    cur = conn.cursor()
    cur.execute("SELECT remaining FROM quota_ledger WHERE provider = 'gemini'")
    remaining = cur.fetchone()[0]
    assert remaining == 85  # 90 - 5
    conn.close()


def test_get_db_connections_returns_tuple():
    """get_db_connections should return (pg_conn, sqlite_conn) tuple."""
    with patch("engine.enrichment_scheduler.psycopg2") as mock_pg:
        mock_pg.connect.return_value = MagicMock()
        pg_conn, sq_conn = get_db_connections("postgresql://fake", ":memory:")
        assert pg_conn is not None
        assert sq_conn is not None
        sq_conn.close()
