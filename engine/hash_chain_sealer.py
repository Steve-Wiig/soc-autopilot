import sys
import os
import hashlib
import logging
import json
import contextlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional, Generator, Iterator

import psycopg2
from psycopg2.extras import execute_values

DEFAULT_LOCK_ID = 37001
DEFAULT_BATCH_SIZE = 10000
GENESIS_HASH = (
    "0000000000000000000000000000000000000000000000000000000000000000"
)

logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Standard LogRecord attributes are mapped to a fixed set of JSON fields
    (timestamp, level, message, module, function, line, exception). Any
    additional attributes attached via `extra=` are included as-is.
    """

    # Known standard LogRecord attributes (whitelist of standard fields)
    # Source: Python logging.LogRecord documentation
    _STANDARD_ATTRS = {
        "name", "msg", "args", "created", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs",
        "message", "pathname", "process", "processName",
        "relativeCreated", "thread", "threadName", "exc_info",
        "exc_text", "stack_info", "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Render a LogRecord as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            A JSON-encoded string representing the log record.
        """
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_ATTRS:
                log_data[key] = value
        return json.dumps(log_data)


def _acquire_lock(cursor: psycopg2.extensions.cursor, lock_id: int) -> None:
    """Acquire a PostgreSQL advisory lock, blocking until it is available.

    Args:
        cursor: Database cursor used to issue the lock command.
        lock_id: PostgreSQL advisory lock ID to acquire.
    """
    cursor.execute("SELECT pg_advisory_lock(%s)", (lock_id,))


def _release_lock(cursor: Optional[psycopg2.extensions.cursor], lock_id: int) -> None:
    """Release a previously acquired PostgreSQL advisory lock.

    Args:
        cursor: Database cursor used to issue the unlock command. If None,
            this is a no-op.
        lock_id: PostgreSQL advisory lock ID to release.

    Raises:
        Exception: Re-raises any error encountered while releasing the lock,
            after logging it, so failures are never silently swallowed.
    """
    if cursor:
        try:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
        except Exception as e:
            # HARDENED: Fail closed with telemetry
            logger.error(f"CONTROL-PLANE FAILURE in hash_chain_sealer.py: {e}")
            raise


def get_last_chain_state(cursor: psycopg2.extensions.cursor) -> Tuple[int, str]:
    """Retrieve the latest chain sequence number and hash from audit_chain.

    Args:
        cursor: Database cursor for executing the query.

    Returns:
        A tuple of (chain_seq, row_hash). Returns (0, GENESIS_HASH) if the
        audit_chain table is empty.
    """
    cursor.execute(
        """
        SELECT chain_seq, row_hash
        FROM audit_chain
        ORDER BY chain_seq DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if row is None:
        return 0, GENESIS_HASH
    return row[0], row[1]


def create_pending_cursor(conn: psycopg2.extensions.connection) -> psycopg2.extensions.cursor:
    """Create a server-side cursor for unprocessed handoffs.

    The cursor selects handoffs that have not yet been added to audit_chain,
    ordered by timestamp then ID.

    Args:
        conn: Database connection used to create the cursor.

    Returns:
        A named, holdable cursor positioned at the first pending handoff.
    """
    pending_cursor = conn.cursor(name="pending_cursor", withhold=True)
    pending_cursor.execute(
        """
        SELECT h.id, h.ts, h.payload_sha256
        FROM handoffs h
        LEFT JOIN audit_chain a ON a.row_id = h.id
        WHERE a.row_id IS NULL
        ORDER BY h.ts ASC, h.id ASC
        """
    )
    return pending_cursor


def fetch_pending_batches(
    pending_cursor: psycopg2.extensions.cursor,
    batch_size: int,
) -> Generator[List[Tuple], None, None]:
    """Yield batches of pending handoff rows from the cursor.

    Args:
        pending_cursor: Server-side cursor returned by create_pending_cursor.
        batch_size: Maximum number of rows per batch.

    Yields:
        Lists of tuples (id, ts, payload_sha256) for each batch. Stops when
        the cursor is exhausted.
    """
    while True:
        pending_rows = pending_cursor.fetchmany(batch_size)
        if not pending_rows:
            break
        yield pending_rows


def compute_chain_hashes(
    batch: List[Tuple],
    last_seq: int,
    prev_hash: str,
) -> Tuple[List[Tuple], int, str]:
    """Compute chain hashes for a batch of handoff rows.

    Each row's hash incorporates the sequence number, previous row's hash,
    and the payload SHA256, forming a tamper-evident chain.

    Args:
        batch: List of (row_id, row_ts, payload_sha256) tuples.
        last_seq: The last used chain sequence number.
        prev_hash: The hash of the previous row in the chain (or GENESIS_HASH).

    Returns:
        A tuple of (rows_to_insert, new_last_seq, new_prev_hash) where
        rows_to_insert contains tuples ready for insertion into audit_chain.
    """
    rows_to_insert = []
    for row_id, row_ts, payload_sha in batch:
        if not isinstance(payload_sha, str):
            raise ValueError(f"payload_sha must be a string, got {type(payload_sha).__name__}")
        if len(payload_sha) != 64:
            raise ValueError(f"payload_sha must be 64 hex characters (SHA256), got length {len(payload_sha)}")
        try:
            int(payload_sha, 16)
        except ValueError:
            raise ValueError(f"payload_sha must be valid hexadecimal, got: {payload_sha}")

        last_seq += 1
        hasher = hashlib.sha256()
        hasher.update(str(last_seq).encode("utf-8"))
        hasher.update(prev_hash.encode("utf-8"))
        hasher.update(payload_sha.encode("utf-8"))
        row_hash = hasher.hexdigest()
        rows_to_insert.append(
            (
                last_seq,
                "handoffs",
                row_id,
                row_ts,
                payload_sha,
                prev_hash,
                row_hash,
            )
        )
        prev_hash = row_hash
    return rows_to_insert, last_seq, prev_hash


def insert_chain_links(cursor: psycopg2.extensions.cursor, rows_to_insert: List[Tuple]) -> None:
    """Insert computed chain links into audit_chain using bulk insert.

    Args:
        cursor: Database cursor for executing the insert.
        rows_to_insert: List of tuples matching audit_chain columns:
            (chain_seq, table_name, row_id, row_ts, canonical_payload_sha256,
             previous_hash, row_hash).
    """
    insert_query = """
        INSERT INTO audit_chain
        (chain_seq, table_name, row_id, row_ts, canonical_payload_sha256,
         previous_hash, row_hash)
        VALUES %s
    """
    execute_values(cursor, insert_query, rows_to_insert)


def _close_cursor_safely(cursor: Optional[psycopg2.extensions.cursor]) -> None:
    """Close a database cursor, logging and re-raising on failure.

    Args:
        cursor: Cursor to close. If None, this is a no-op.

    Raises:
        Exception: Re-raises any error encountered while closing the cursor,
            after logging it, so failures are never silently swallowed.
    """
    if cursor:
        try:
            cursor.close()
        except Exception as e:
            # HARDENED: Fail closed with telemetry
            logger.error(f"CONTROL-PLANE FAILURE in hash_chain_sealer.py: {e}")
            raise


def _close_connection_safely(conn: Optional[psycopg2.extensions.connection]) -> None:
    """Close a database connection, logging and re-raising on failure.

    Args:
        conn: Connection to close. If None, this is a no-op.

    Raises:
        Exception: Re-raises any error encountered while closing the
            connection, after logging it, so failures are never silently
            swallowed.
    """
    if conn:
        try:
            conn.close()
        except Exception as e:
            # HARDENED: Fail closed with telemetry
            logger.error(f"CONTROL-PLANE FAILURE in hash_chain_sealer.py: {e}")
            raise


@contextlib.contextmanager
def _advisory_lock(cursor: psycopg2.extensions.cursor, lock_id: int) -> Iterator[None]:
    """Context manager that acquires and releases a PostgreSQL advisory lock.

    Args:
        cursor: Database cursor used to issue lock/unlock commands.
        lock_id: PostgreSQL advisory lock ID to acquire for the duration of
            the `with` block.

    Yields:
        None.
    """
    _acquire_lock(cursor, lock_id)
    try:
        yield
    finally:
        _release_lock(cursor, lock_id)


def _process_pending_batches(
    conn: psycopg2.extensions.connection,
    cursor: psycopg2.extensions.cursor,
    pending_cursor: psycopg2.extensions.cursor,
    batch_size: int,
    last_seq: int,
    prev_hash: str,
) -> Tuple[int, str, int]:
    """Process all pending handoff batches, sealing each into the audit chain.

    Fetches batches from `pending_cursor`, computes chain hashes for each
    batch, inserts the resulting rows into audit_chain, and commits after
    every batch.

    Args:
        conn: Database connection, used to commit after each batch.
        cursor: Cursor used to insert the computed chain links.
        pending_cursor: Server-side cursor yielding pending handoff rows.
        batch_size: Maximum number of rows to fetch per batch.
        last_seq: The last used chain sequence number.
        prev_hash: The hash of the previous row in the chain.

    Returns:
        A tuple of (new_last_seq, new_prev_hash, pending_count) reflecting
        the final chain state and the total number of rows processed.
    """
    current_seq = last_seq
    current_hash = prev_hash
    pending_count = 0
    for batch in fetch_pending_batches(pending_cursor, batch_size):
        rows_to_insert, current_seq, current_hash = compute_chain_hashes(
            batch, current_seq, current_hash
        )
        insert_chain_links(cursor, rows_to_insert)
        conn.commit()
        pending_count += len(rows_to_insert)
    return current_seq, current_hash, pending_count


def seal_audit_chain_with_connection(
    conn: psycopg2.extensions.connection,
    lock_id: int = DEFAULT_LOCK_ID,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """Seal the audit chain using an existing database connection.

    Acquires an advisory lock, reads the last chain state, processes all
    pending handoffs in batches, computes chain hashes, and inserts them
    into audit_chain. Commits after each batch.

    Args:
        conn: Open psycopg2 connection (caller manages lifecycle).
        lock_id: PostgreSQL advisory lock ID to serialize concurrent sealers.
        batch_size: Number of handoffs to process per batch.

    Raises:
        RuntimeError: If any error occurs during sealing; the transaction
            is rolled back before raising.
    """
    last_seq = 0
    prev_hash = GENESIS_HASH
    pending_count = 0

    try:
        with conn.cursor() as cursor:
            with _advisory_lock(cursor, lock_id):
                last_seq, prev_hash = get_last_chain_state(cursor)

                with create_pending_cursor(conn) as pending_cursor:
                    last_seq, prev_hash, pending_count = _process_pending_batches(
                        conn, cursor, pending_cursor, batch_size, last_seq, prev_hash
                    )

    except Exception as e:
        logger.error(
            "Sealer failed",
            extra={
                "lock_id": lock_id,
                "batch_size": batch_size,
                "pending_count": pending_count,
                "last_seq": last_seq,
            },
            exc_info=True,
        )
        if conn:
            conn.rollback()
        raise RuntimeError(f"Sealer failed: {e}") from e


def seal_audit_chain(
    db_config: Dict[str, Any],
    lock_id: int = DEFAULT_LOCK_ID,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """Open a connection and seal the audit chain.

    Convenience wrapper that creates a connection from db_config, calls
    seal_audit_chain_with_connection, and ensures the connection is closed.

    Args:
        db_config: Dictionary of psycopg2 connection parameters (dbname, user,
            password, host, port).
        lock_id: PostgreSQL advisory lock ID to serialize concurrent sealers.
        batch_size: Number of handoffs to process per batch.

    Raises:
        RuntimeError: Propagated from seal_audit_chain_with_connection on failure.
    """
    conn = None
    try:
        conn = psycopg2.connect(**db_config)
        seal_audit_chain_with_connection(conn, lock_id, batch_size)
    finally:
        _close_connection_safely(conn)


def _load_config() -> Dict[str, Any]:
    """Load configuration from environment variables.

    Required: SOC_DBNAME, SOC_USER.
    Optional: SOC_PASSWORD, SOC_HOST, SOC_PORT, SOC_BATCH_SIZE.

    Returns:
        Dictionary with keys 'db_config' (connection params dict) and
        'batch_size' (int).

    Raises:
        RuntimeError: If required environment variables are missing or SOC_BATCH_SIZE is invalid.
    """
    required_vars = ["SOC_DBNAME", "SOC_USER"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    db_config = {
        "dbname": os.getenv("SOC_DBNAME"),
        "user": os.getenv("SOC_USER"),
    }
    if password := os.getenv("SOC_PASSWORD"):
        db_config["password"] = password
    if host := os.getenv("SOC_HOST"):
        db_config["host"] = host
    if port := os.getenv("SOC_PORT"):
        db_config["port"] = int(port)

    batch_size = DEFAULT_BATCH_SIZE
    if batch_size_env := os.getenv("SOC_BATCH_SIZE"):
        try:
            batch_size = int(batch_size_env)
        except ValueError as e:
            raise RuntimeError(f"Invalid SOC_BATCH_SIZE value '{batch_size_env}': must be an integer") from e

    return {"db_config": db_config, "batch_size": batch_size}


def configure_logging() -> None:
    """Configure root logger with a JSON formatter writing to stderr.

    This is idempotent: if the root logger already has handlers attached,
    it is left untouched.
    """
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)


def main() -> None:
    """Entry point: configure logging, load config, and seal the audit chain."""
    configure_logging()
    config = _load_config()
    seal_audit_chain(config["db_config"], batch_size=config["batch_size"])


if __name__ == "__main__":
    main()
