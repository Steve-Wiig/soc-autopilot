"""SQLite-backed quota ledger for tracking and enforcing per-adapter token usage.

This module provides:
- Schema initialization for the quota ledger, approvals, and audit tables.
- Quota checks (`check_quota`) and usage recording (`record_usage`).
- Approval token creation and validation for SOC audit compliance.
- A CLI entry point (`main`) for scripting/administration.
- Optional thread-local connection pooling controlled via the
  QUOTA_LEDGER_POOL_CONNECTIONS environment variable.
"""

import sqlite3
import argparse
import sys
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Optional


def _get_default_db_path() -> str:
    """Get default database path from environment variable or fallback."""
    return os.environ.get("QUOTA_LEDGER_DB_PATH", "quota_ledger.db")


def _get_pool_enabled() -> bool:
    """Check if connection pooling is enabled via environment variable."""
    return os.environ.get("QUOTA_LEDGER_POOL_CONNECTIONS", "false").lower() in ("1", "true", "yes")


DB_PATH = _get_default_db_path()
_POOL_ENABLED = _get_pool_enabled()


class _ThreadLocalConnectionCache(threading.local):
    """Typed thread-local storage for a single pooled SQLite connection per thread.

    Attributes:
        conn: The cached connection for the current thread, or None if not yet created.
        db_path: The database path the cached connection was opened against, or None.
    """
    conn: Optional[sqlite3.Connection] = None
    db_path: Optional[str] = None


_thread_local = _ThreadLocalConnectionCache()


class QuotaLedgerError(Exception):
    """Base exception for quota ledger errors."""
    pass


class QuotaExceededError(QuotaLedgerError):
    """Raised when an adapter's quota is exceeded."""
    pass


class QuotaAdapterNotFoundError(QuotaLedgerError):
    """Raised when an adapter is not found in the ledger.

    Note: This exception is reserved for future use. Currently,
    `check_quota` returns False rather than raising this when an
    adapter is not found in the ledger.
    """
    pass


class ApprovalValidationError(QuotaLedgerError):
    """Raised when an approval token is invalid or missing."""
    pass


def _get_pooled_connection(db_path: str) -> sqlite3.Connection:
    """Get or create the thread-local pooled connection for the given database path.

    If a pooled connection already exists for this thread but points at a
    different database path, it is closed and replaced with a new connection
    to `db_path`.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        A live sqlite3.Connection cached for the current thread.
    """
    if _thread_local.conn is None:
        _thread_local.conn = sqlite3.connect(db_path, check_same_thread=False)
        _thread_local.conn.execute("PRAGMA foreign_keys = ON")
    elif _thread_local.db_path != db_path:
        _thread_local.conn.close()
        _thread_local.conn = sqlite3.connect(db_path, check_same_thread=False)
        _thread_local.conn.execute("PRAGMA foreign_keys = ON")
    _thread_local.db_path = db_path
    return _thread_local.conn


def _release_pooled_connection() -> None:
    """Close and clear the thread-local pooled connection, if one exists."""
    if _thread_local.conn is not None:
        _thread_local.conn.close()
        _thread_local.conn = None
        _thread_local.db_path = None


@contextmanager
def get_db_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections with automatic commit/rollback.

    If connection pooling is enabled (QUOTA_LEDGER_POOL_CONNECTIONS=1), reuses a
    thread-local connection instead of creating a new one each time.

    Args:
        db_path: Optional database path. Defaults to the module-level DB_PATH
            (which itself defaults to the QUOTA_LEDGER_DB_PATH env var or
            "quota_ledger.db").

    Yields:
        An active sqlite3.Connection. Commits on successful exit, rolls back
        and raises QuotaLedgerError on sqlite3.Error.

    Raises:
        QuotaLedgerError: If a database error occurs during the transaction.
    """
    resolved_path = db_path or DB_PATH

    if _POOL_ENABLED:
        conn = _get_pooled_connection(resolved_path)
        try:
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise QuotaLedgerError(f"Database error: {e}") from e
    else:
        conn = sqlite3.connect(resolved_path)
        try:
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            raise QuotaLedgerError(f"Database error: {e}") from e
        finally:
            conn.close()


def close_connection_pool() -> None:
    """Close the thread-local pooled connection if pooling is enabled.

    Call this at thread shutdown or application exit to clean up resources.
    """
    if _POOL_ENABLED:
        _release_pooled_connection()


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes the quota ledger database and creates the table if it does not exist.

    Args:
        db_path: Optional database path for testing.

    Raises:
        QuotaLedgerError: If database initialization fails.
    """
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quota_ledger (
                    adapter_id TEXT PRIMARY KEY,
                    daily_limit INTEGER NOT NULL CHECK (daily_limit > 0),
                    job_limit INTEGER NOT NULL CHECK (job_limit > 0),
                    tokens_used_today INTEGER DEFAULT 0,
                    last_reset_date TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    adapter_id TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    used_at TEXT,
                    max_tokens INTEGER NOT NULL CHECK (max_tokens > 0),
                    tokens_used INTEGER DEFAULT 0
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quota_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    adapter_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    tokens_delta INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    previous_total INTEGER NOT NULL,
                    new_total INTEGER NOT NULL,
                    approval_token TEXT,
                    approval_id TEXT
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_quota_audit_adapter_id ON quota_audit(adapter_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_quota_audit_timestamp ON quota_audit(timestamp)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_approvals_adapter_id ON approvals(adapter_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_approvals_token ON approvals(token)
            ''')
    except sqlite3.Error as e:
        raise QuotaLedgerError(f"Database initialization failed: {e}") from e


def _get_effective_daily_usage(tokens_used_today: int, last_reset_date: str, today: str) -> int:
    """Compute the effective daily token usage, accounting for day rollover.

    If the stored last reset date differs from today's date, the daily
    counter is treated as having been reset to zero (the rollover is applied
    lazily at read/write time rather than via a scheduled job).

    Args:
        tokens_used_today: The tokens_used_today value currently stored for the adapter.
        last_reset_date: The last_reset_date value currently stored for the adapter.
        today: Today's date string, in the same format as last_reset_date (YYYY-MM-DD).

    Returns:
        The effective token usage count for today.
    """
    if last_reset_date != today:
        return 0
    return tokens_used_today


def _validate_approval(cursor: sqlite3.Cursor, adapter_id: str, approval_token: str, tokens_requested: int) -> str:
    """Validate approval token and return approval_id.

    Args:
        cursor: Database cursor.
        adapter_id: The adapter identifier.
        approval_token: The approval token to validate.
        tokens_requested: Number of tokens being requested.

    Returns:
        The approval_id if valid.

    Raises:
        ApprovalValidationError: If approval is invalid, expired, or exhausted.
    """
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "SELECT approval_id, expires_at, max_tokens, tokens_used FROM approvals WHERE token = ? AND adapter_id = ?",
        (approval_token, adapter_id)
    )
    row = cursor.fetchone()

    if not row:
        raise ApprovalValidationError("Invalid approval token for adapter")

    approval_id, expires_at, max_tokens, tokens_used = row

    if expires_at and expires_at < now:
        raise ApprovalValidationError("Approval token has expired")

    if (tokens_used + tokens_requested) > max_tokens:
        raise ApprovalValidationError("Approval token token limit exceeded")

    return approval_id


def _mark_approval_used(cursor: sqlite3.Cursor, approval_token: str, tokens_used: int) -> None:
    """Mark approval as used and update tokens_used.

    Args:
        cursor: Database cursor.
        approval_token: The approval token to update.
        tokens_used: Number of tokens to add to the approval's running total.
    """
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "UPDATE approvals SET tokens_used = tokens_used + ?, used_at = ? WHERE token = ?",
        (tokens_used, now, approval_token)
    )


def check_quota(adapter_id: str, estimated_tokens: int, db_path: Optional[str] = None) -> bool:
    """Checks if an adapter has sufficient quota for a given token usage.

    Args:
        adapter_id: The unique identifier for the adapter.
        estimated_tokens: The number of tokens to be used.
        db_path: Optional database path for testing.

    Returns:
        True if the usage is within limits, False otherwise (including when
        the adapter is not found in the ledger).

    Raises:
        QuotaLedgerError: If a database error occurs during the quota check.
    """
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            cursor.execute(
                "SELECT daily_limit, job_limit, tokens_used_today, last_reset_date FROM quota_ledger WHERE adapter_id = ?",
                (adapter_id,)
            )
            row = cursor.fetchone()

        if not row:
            return False

        daily_limit, job_limit, tokens_used_today, last_reset_date = row
        effective_usage = _get_effective_daily_usage(tokens_used_today, last_reset_date, today)

        if (effective_usage + estimated_tokens) > daily_limit or estimated_tokens > job_limit:
            return False
        return True
    except sqlite3.Error as e:
        raise QuotaLedgerError(f"Database error during quota check: {e}") from e


def record_usage(adapter_id: str, tokens_used: int, db_path: Optional[str] = None, approval_token: Optional[str] = None) -> None:
    """Records token usage for a specific adapter in the database.

    Args:
        adapter_id: The unique identifier for the adapter.
        tokens_used: The number of tokens to record.
        db_path: Optional database path for testing.
        approval_token: Optional approval token for SOC audit compliance.

    Raises:
        ApprovalValidationError: If approval_token is provided but invalid.
        QuotaLedgerError: If database error occurs.
    """
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            timestamp = datetime.now(timezone.utc).isoformat()

            cursor.execute(
                "SELECT tokens_used_today, last_reset_date FROM quota_ledger WHERE adapter_id = ?",
                (adapter_id,)
            )
            row = cursor.fetchone()

            if row:
                tokens_used_today, last_reset_date = row
                previous_total = tokens_used_today if last_reset_date == today else 0
                new_total = previous_total + tokens_used

                approval_id = None
                if approval_token:
                    approval_id = _validate_approval(cursor, adapter_id, approval_token, tokens_used)
                    _mark_approval_used(cursor, approval_token, tokens_used)

                cursor.execute(
                    "UPDATE quota_ledger SET tokens_used_today = ?, last_reset_date = ? WHERE adapter_id = ?",
                    (new_total, today, adapter_id)
                )
                cursor.execute(
                    "INSERT INTO quota_audit (adapter_id, timestamp, tokens_delta, operation, previous_total, new_total, approval_token, approval_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (adapter_id, timestamp, tokens_used, 'usage', previous_total, new_total, approval_token, approval_id)
                )
    except sqlite3.Error as e:
        raise QuotaLedgerError(f"Database error during usage recording: {e}") from e


def create_approval(adapter_id: str, approval_token: str, max_tokens: int, expires_at: Optional[str] = None, db_path: Optional[str] = None) -> str:
    """Create a new approval token for an adapter.

    Args:
        adapter_id: The adapter identifier.
        approval_token: Unique token string for the approval.
        max_tokens: Maximum tokens this approval allows.
        expires_at: Optional ISO format expiration timestamp.
        db_path: Optional database path for testing.

    Returns:
        The generated approval_id.

    Raises:
        QuotaLedgerError: If a database error occurs while creating the approval.
    """
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            approval_id = f"appr_{adapter_id}_{int(datetime.now(timezone.utc).timestamp())}"
            created_at = datetime.now(timezone.utc).isoformat()

            cursor.execute(
                "INSERT INTO approvals (approval_id, adapter_id, token, created_at, expires_at, max_tokens) VALUES (?, ?, ?, ?, ?, ?)",
                (approval_id, adapter_id, approval_token, created_at, expires_at, max_tokens)
            )
            return approval_id
    except sqlite3.Error as e:
        raise QuotaLedgerError(f"Database error creating approval: {e}") from e


def main() -> int:
    """Parses command line arguments and executes the requested quota management operation.

    Returns:
        int: Process exit code.
            0 = success (init completed / check passed / usage recorded)
            1 = check failed (quota exceeded or adapter not found)
            2 = no operation specified (usage error)
    """
    parser = argparse.ArgumentParser(description="SLM Quota Ledger Manager")
    parser.add_argument("--db-path", default=DB_PATH, help="Path to SQLite database (default: quota_ledger.db or QUOTA_LEDGER_DB_PATH env var)")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--check", nargs=2, metavar=('ID', 'TOKENS'))
    parser.add_argument("--record", nargs=2, metavar=('ID', 'TOKENS'))
    parser.add_argument("--approval-token", help="Approval token for SOC audit compliance")
    parser.add_argument("--create-approval", nargs=3, metavar=('ID', 'TOKEN', 'MAX_TOKENS'), help="Create approval: adapter_id, token, max_tokens")
    parser.add_argument("--expires-at", help="Expiration timestamp for approval (ISO format)")
    args = parser.parse_args()

    db_path = args.db_path

    if args.init:
        init_db(db_path)
        return 0
    elif args.check:
        if check_quota(args.check[0], int(args.check[1]), db_path):
            return 0
        else:
            return 1
    elif args.record:
        record_usage(args.record[0], int(args.record[1]), db_path, args.approval_token)
        return 0
    elif args.create_approval:
        adapter_id, token, max_tokens = args.create_approval
        create_approval(adapter_id, token, int(max_tokens), args.expires_at, db_path)
        return 0
    else:
        return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        close_connection_pool()
