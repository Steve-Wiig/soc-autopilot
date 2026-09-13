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
    # Known standard LogRecord attributes (whitelist of standard fields)
    # Source: Python logging.LogRecord documentation
    _STANDARD_ATTRS = {
        "name", "msg", "args", "created", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs",
        "message", "pathname", "process", "processName",
        "relativeCreated", "thread", "threadName", "exc_info",
        "exc_text", "stack_info", "asctime", "relativeCreated"
    }

    def format(self, record: logging.LogRecord) -> str:
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

def _acquire_lock(cur: psycopg2.extensions.cursor, lock_id: int) -> None:
    cur.execute("SELECT pg_advisory_lock(%s)", (lock_id,))


def _release_lock(cur: Optional[psycopg2.extensions.cursor], lock_id: int) -> None:
    if cur:
        try:
            cur.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
        except Exception as e:
            # HARDENED: Fail closed with telemetry
            import logging
            logging.error(f'CONTROL-PLANE FAILURE in hash_chain_sealer.py: {e}')
            raise


def get_last_chain_state(cur: psycopg2.extensions.cursor) -> Tuple[int, str]:
    """Retrieve the latest chain sequence number and hash from audit_chain.

    Args:
        cur: Database cursor for executing the query.

    Returns:
        A tuple of (chain_seq, row_hash). Returns (0, GENESIS_HASH) if the
        audit_chain table is empty.
    """
    cur.execute(
        """
        SELECT chain_seq, row_hash
        FROM audit_chain
        ORDER BY chain_seq DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
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
    pending_cur = conn.cursor(name="pending_cursor", withhold=True)
    pending_cur.execute(
        """
        SELECT h.id, h.ts, h.payload_sha256
        FROM handoffs h
        LEFT JOIN audit_chain a ON a.row_id = h.id
        WHERE a.row_id IS NULL
        ORDER BY h.ts ASC, h.id ASC
        """
    )
    return pending_cur

def fetch_pending_batches(
    pending_cur: psycopg2.extensions.cursor,
    batch_size: int,
) -> Generator[List[Tuple], None, None]:
    """Yield batches of pending handoff rows from the cursor.

    Args:
        pending_cur: Server-side cursor returned by create_pending_cursor.
        batch_size: Maximum number of rows per batch.

    Yields:
        Lists of tuples (id, ts, payload_sha256) for each batch. Stops when
        the cursor is exhausted.
    """
    while True:
        pending_rows = pending_cur.fetchmany(batch_size)
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
def insert_chain_links(cur: psycopg2.extensions.cursor, rows_to_insert: List[Tuple]) -> None:
    """Insert computed chain links into audit_chain using bulk insert.

    Args:
        cur: Database cursor for executing the insert.
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
    execute_values(cur, insert_query, rows_to_insert)


def _close_cursor_safely(cur: Optional[psycopg2.extensions.cursor]) -> None:
    if cur:
        try:
            cur.close()
        except Exception as e:
            # HARDENED: Fail closed with telemetry
            import logging
            logging.error(f'CONTROL-PLANE FAILURE in hash_chain_sealer.py: {e}')
            raise


def _close_connection_safely(conn: Optional[psycopg2.extensions.connection]) -> None:
    if conn:
        try:
            conn.close()
        except Exception as e:
            # HARDENED: Fail closed with telemetry
            import logging
            logging.error(f'CONTROL-PLANE FAILURE in hash_chain_sealer.py: {e}')
            raise


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
    @contextlib.contextmanager
    def _lock_context(cursor: psycopg2.extensions.cursor, lock_id: int) -> Iterator[None]:
        _acquire_lock(cursor, lock_id)
        try:
            yield
        finally:
            _release_lock(cursor, lock_id)

    def _process_batches(
        cursor: psycopg2.extensions.cursor,
        pending_cursor: psycopg2.extensions.cursor,
        batch_size: int,
        last_seq: int,
        prev_hash: str,
    ) -> Tuple[int, str]:
        current_seq = last_seq
        current_hash = prev_hash
        for batch in fetch_pending_batches(pending_cursor, batch_size):
            rows_to_insert, current_seq, current_hash = compute_chain_hashes(
                batch, current_seq, current_hash
            )
            insert_chain_links(cursor, rows_to_insert)
            conn.commit()
        return current_seq, current_hash

    last_seq = 0
    prev_hash = GENESIS_HASH
    pending_count = 0

    try:
        with conn.cursor() as cur:
            with _lock_context(cur, lock_id):
                last_seq, prev_hash = get_last_chain_state(cur)

                with create_pending_cursor(conn) as pending_cur:
                    last_seq, prev_hash = _process_batches(
                        cur, pending_cur, batch_size, last_seq, prev_hash
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
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

def main() -> None:
    configure_logging()
    config = _load_config()
    seal_audit_chain(config["db_config"], batch_size=config["batch_size"])


if __name__ == "__main__":
    main()