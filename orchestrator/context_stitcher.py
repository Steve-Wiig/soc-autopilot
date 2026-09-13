import psycopg2
import psycopg2.extensions
import psycopg2.pool
import sys
import hashlib
import json
import struct
import io
import threading
import os
from datetime import datetime, timezone, timedelta
from typing import TypedDict, Optional, Callable
from xml.sax.saxutils import escape
from dataclasses import dataclass


_PG_POOL_MINCONN = int(os.getenv('PG_POOL_MINCONN', '1'))
_PG_POOL_MAXCONN = int(os.getenv('PG_POOL_MAXCONN', '10'))
MAX_TOP_K = 100


def configure_connection(
    dbname: str = "soc_db",
    user: str = "orchestrator",
    minconn: int = _PG_POOL_MINCONN,
    maxconn: int = _PG_POOL_MAXCONN,
    **kwargs
) -> Callable[[], psycopg2.pool.ThreadedConnectionPool]:
    """Configure database connection pool parameters and return a pool factory."""
    pool_params = {"dbname": dbname, "user": user, **kwargs}
    min_conn = minconn
    max_conn = maxconn

    def pool_factory() -> psycopg2.pool.ThreadedConnectionPool:
        return psycopg2.pool.ThreadedConnectionPool(
            minconn=min_conn,
            maxconn=max_conn,
            **pool_params
        )

    return pool_factory


_DEFAULT_POOL_FACTORY: Optional[Callable[[], psycopg2.pool.ThreadedConnectionPool]] = None
_DEFAULT_POOL: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_DEFAULT_POOL_LOCK = threading.Lock()


def _get_default_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Get or create the default PostgreSQL connection pool."""
    global _DEFAULT_POOL, _DEFAULT_POOL_FACTORY
    if not hasattr(_get_default_pool, "_lock"):
        _get_default_pool._lock = threading.Lock()
    with _get_default_pool._lock:
        if _DEFAULT_POOL is None:
            if _DEFAULT_POOL_FACTORY is None:
                _DEFAULT_POOL_FACTORY = configure_connection()
            _DEFAULT_POOL = _DEFAULT_POOL_FACTORY()
        return _DEFAULT_POOL

def _get_pg_conn(pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None) -> psycopg2.extensions.connection:
    """Acquire a connection from the pool."""
    if pool is None:
        pool = _get_default_pool()
    return pool.getconn()


def _put_pg_conn(conn: psycopg2.extensions.connection, pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None) -> None:
    """Return a connection to the pool."""
    if pool is None:
        pool = _DEFAULT_POOL
    if pool is not None:
        try:
            pool.putconn(conn)
        except Exception:
            try:
                conn.close()
            except Exception as e:
                # HARDENED: Fail closed with telemetry
                import logging
                logging.error(f'CONTROL-PLANE FAILURE in context_stitcher.py: {e}')
                raise


class DatabaseError(Exception):
    """Custom exception for database-related failures in stitch_memory_context."""
    pass


class StitcherError(Exception):
    """Custom exception for stitching logic failures in stitch_memory_context."""
    pass


class MemoryMetadata(TypedDict):
    """Type definition for memory retrieval metadata."""
    memory_retrieval_timestamp: str
    retrieved_case_ids: list[str]
    top_k_requested: int
    max_age_days: int


@dataclass
class AuditLogEntry:
    """Data class for audit log entry fields."""
    retrieval_timestamp: datetime
    query_hash: str
    case_ids: list[str]
    top_k: int
    max_age_days: int
    audit_context: Optional[dict] = None


def _compute_query_hash(query_embedding: list[float]) -> str:
    """Compute a deterministic SHA256 hash of the query embedding for audit logging."""
    h = hashlib.sha256()
    for v in query_embedding:
        h.update(struct.pack('d', v))
    return h.hexdigest()


def _log_audit(
    conn: psycopg2.extensions.connection,
    entry: AuditLogEntry
) -> None:
    """Insert an audit log entry for the memory retrieval operation."""
    
    def _handle_audit_failure(conn, query_hash, error, error_type):
        print(
            f"AUDIT LOG FAILURE ({error_type}): query_hash={query_hash}, case_ids={entry.case_ids}, "
            f"top_k={entry.top_k}, max_age_days={entry.max_age_days}, error={error}",
            file=sys.stderr,
        )
        try:
            conn.rollback()
        except psycopg2.Error as rb_err:
            print(f"AUDIT ROLLBACK FAILURE: query_hash={query_hash}, error={rb_err}", file=sys.stderr)
        if error_type == "psycopg2.Error":
            raise RuntimeError(f"Failed to write audit log for query_hash={query_hash}") from error
        else:
            raise RuntimeError(f"Audit context serialization failed for query_hash={query_hash}") from error

    cur = None
    try:
        cur = conn.cursor()
        audit_query = """
            INSERT INTO memory_retrieval_audit (retrieval_timestamp, query_hash, case_ids, top_k, max_age_days, audit_context)
            VALUES (%s, %s, %s, %s, %s, %s);
        """
        context_json = json.dumps(entry.audit_context) if entry.audit_context is not None else None
        cur.execute(audit_query, (entry.retrieval_timestamp, entry.query_hash, entry.case_ids, entry.top_k, entry.max_age_days, context_json))
        conn.commit()
    except psycopg2.Error as e:
        _handle_audit_failure(conn, entry.query_hash, e, "psycopg2.Error")
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        _handle_audit_failure(conn, entry.query_hash, e, "serialization error")
    finally:
        if cur is not None:
            cur.close()
def stitch_memory_context(
    query_embedding: list[float],
    top_k: int = 5,
    max_age_days: int = 30,
    conn: Optional[psycopg2.extensions.connection] = None,
    pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None,
    audit_context: Optional[dict] = None
) -> tuple[str, MemoryMetadata]:
    """
    Queries case_embeddings for semantic recall and formats for SLM injection.

    Args:
        query_embedding: List of floats representing the query vector for cosine similarity search.
        top_k: Maximum number of similar cases to retrieve. Defaults to 5.
        max_age_days: Maximum age of cases to consider in days. Defaults to 30.
        conn: Optional psycopg2 connection to use. If not provided, acquires from pool.
        pool: Optional connection pool to use. If not provided, uses default pool.
        audit_context: Optional dictionary containing requestor/approval context for compliance audit trail.

    Returns:
        A tuple containing:
        - formatted_context (str): XML-formatted string with retrieved case summaries and distances.
        - metadata (MemoryMetadata): Dictionary with retrieval metadata including timestamp, case IDs, and parameters.

    Raises:
        DatabaseError: If a psycopg2 database error occurs during query execution or connection.
        StitcherError: If an unexpected error occurs during memory context stitching.
    """
    top_k = min(top_k, MAX_TOP_K)
    use_pool = conn is None
    if use_pool:
        conn = _get_pg_conn(pool)
    
    cur = None
    try:
        cur = conn.cursor()

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        results, case_refs = _execute_similarity_query(cur, query_embedding, cutoff_date, top_k)
        formatted_context = _format_context_blocks(results)
        retrieval_timestamp = datetime.now(timezone.utc)
        metadata = _build_metadata(retrieval_timestamp, case_refs, top_k, max_age_days)

        query_hash = _compute_query_hash(query_embedding)
        audit_entry = AuditLogEntry(
            retrieval_timestamp=retrieval_timestamp,
            query_hash=query_hash,
            case_ids=case_refs,
            top_k=top_k,
            max_age_days=max_age_days,
            audit_context=audit_context
        )
        _log_audit(conn, audit_entry)
        
        return formatted_context, metadata

    except psycopg2.Error as e:
        raise DatabaseError(f"Failed to retrieve memory context from database: {e}") from e
    except Exception as e:
        raise StitcherError(f"Unexpected error during memory context stitching: {e}") from e
    finally:
        if cur is not None:
            cur.close()
        if use_pool and conn is not None:
            _put_pg_conn(conn, pool)
        elif not use_pool and conn is not None:
            try:
                conn.close()
            except Exception as e:
                # HARDENED: Fail closed with telemetry
                import logging
                logging.error(f'CONTROL-PLANE FAILURE in context_stitcher.py: {e}')
                raise
def _execute_similarity_query(cursor: psycopg2.extensions.cursor, embedding: list[float], cutoff: datetime, limit: int) -> tuple[list[tuple], list[str]]:
    query = """
        SELECT case_id, summary, cosine_distance(embedding, %s::vector) as dist
        FROM case_embeddings
        WHERE created_at >= %s
        ORDER BY dist ASC
        LIMIT %s;
    """
    cursor.execute(query, (embedding, cutoff, limit))
    results = cursor.fetchall()
    case_refs = [r[0] for r in results]
    return results, case_refs
def _format_context_blocks(results):
    buffer = io.StringIO()
    buffer.write("<memory_context>\n")
    for r in results:
        buffer.write(f"<case_id={r[0]} dist={r[2]:.4f}>{escape(r[1])}</case_id>")
    buffer.write("\n</memory_context>")
    return buffer.getvalue()

def _build_metadata(timestamp, case_ids, top_k_val, max_age):
    return {
        "memory_retrieval_timestamp": timestamp.isoformat(),
        "retrieved_case_ids": case_ids,
        "top_k_requested": top_k_val,
        "max_age_days": max_age
    }
def set_default_pool_factory(factory: Callable[[], psycopg2.pool.ThreadedConnectionPool]) -> None:
    """Set a custom default pool factory for testing or alternative configurations."""
    global _DEFAULT_POOL_FACTORY, _DEFAULT_POOL
    with _DEFAULT_POOL_LOCK:
        _DEFAULT_POOL_FACTORY = factory
        _DEFAULT_POOL = None
def reset_default_pool() -> None:
    """Reset the default pool (useful for testing)."""
    global _DEFAULT_POOL, _DEFAULT_POOL_FACTORY
    with _DEFAULT_POOL_LOCK:
        pool = _DEFAULT_POOL
        if pool is not None:
            try:
                pool.closeall()
            except Exception as e:
                # HARDENED: Fail closed with telemetry
                import logging
                logging.error(f'CONTROL-PLANE FAILURE in context_stitcher.py: {e}')
                raise
            _DEFAULT_POOL = None
        if _DEFAULT_POOL_FACTORY is not None:
            _DEFAULT_POOL_FACTORY = None

if __name__ == "__main__":
    pass