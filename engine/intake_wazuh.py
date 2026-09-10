import sqlite3
import json
import uuid
import logging
import os
from datetime import datetime, timezone
from typing import Any

from engine.queue_priority import severity_to_priority

try:
    from platformdirs import user_data_dir, user_log_dir
    HAS_PLATFORMDIRS = True
except ImportError:
    HAS_PLATFORMDIRS = False

DB_PATH = os.getenv('TRIAGE_DB_PATH', './data/triage_queue.db')
LOG_FILE = os.getenv('TRIAGE_LOG_FILE', './logs/intake.log')

_connection: sqlite3.Connection | None = None

STATUS_PENDING = 'pending'

ALLOWED_PAYLOAD_KEYS = {'agent', 'rule_id', 'description', 'src_ip', 'dst_ip'}

EXIT_PARSE_ERROR = 2
EXIT_GENERAL_ERROR = 1


class IntakeError(RuntimeError):
    """Base exception for intake errors with an associated exit code."""
    def __init__(self, message: str, exit_code: int = EXIT_GENERAL_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


class ParseError(IntakeError):
    """Raised when JSON parsing fails."""
    def __init__(self, message: str = "Invalid JSON payload"):
        super().__init__(message, EXIT_PARSE_ERROR)


class ValidationError(IntakeError):
    """Raised when payload validation/sanitization fails."""
    def __init__(self, message: str = "Payload validation failed"):
        super().__init__(message, EXIT_GENERAL_ERROR)


class DatabaseError(IntakeError):
    """Raised when database operations fail."""
    def __init__(self, message: str = "Database operation failed"):
        super().__init__(message, EXIT_GENERAL_ERROR)

def _load_config() -> dict[str, str]:
    if HAS_PLATFORMDIRS:
        data_dir = user_data_dir('local-soc', 'local-soc')
        log_dir = user_log_dir('local-soc', 'local-soc')
    else:
        data_dir = os.path.dirname(DB_PATH) or '.'
        log_dir = os.path.dirname(LOG_FILE) or '.'
    
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    
    resolved_db_path = DB_PATH
    resolved_log_file = LOG_FILE
    
    if not os.path.isabs(resolved_db_path):
        resolved_db_path = os.path.join(data_dir, os.path.basename(resolved_db_path))
    if not os.path.isabs(resolved_log_file):
        resolved_log_file = os.path.join(log_dir, os.path.basename(resolved_log_file))
    
    logging.basicConfig(filename=resolved_log_file, level=logging.INFO)
    
    return {
        'db_path': resolved_db_path,
        'log_file': resolved_log_file,
    }
def _get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA busy_timeout=5000")
        _init_audit_table(_connection)
        _init_triage_table(_connection)
    return _connection

def _init_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            alert_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            details TEXT NOT NULL
        )
    """)
    conn.commit()

def _init_triage_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triage_queue (
            id TEXT PRIMARY KEY,
            severity INTEGER NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0
        )
    """)
    index_defs = [
        ('idx_triage_status', 'status'),
        ('idx_triage_severity', 'severity'),
        ('idx_triage_created_at', 'created_at'),
        ('idx_triage_status_severity', 'status, severity')
    ]
    # Query all existing indexes in one round trip
    index_names = [name for name, _ in index_defs]
    placeholders = ','.join('?' * len(index_names))
    cursor = conn.execute(
        f"SELECT name FROM sqlite_master WHERE type='index' AND name IN ({placeholders})",
        tuple(index_names)
    )
    existing = {row[0] for row in cursor.fetchall()}
    for index_name, cols in index_defs:
        if index_name not in existing:
            conn.execute(f"CREATE INDEX {index_name} ON triage_queue({cols})")
    conn.commit()

def _audit_log(conn: sqlite3.Connection, event_type: str, alert_id: str, details: dict[str, Any], correlation_id: str | None = None) -> None:
    audit_details = dict(details)
    if correlation_id is not None:
        audit_details['correlation_id'] = correlation_id
    conn.execute(
        "INSERT INTO audit_log (event_type, alert_id, timestamp, details) VALUES (?, ?, ?, ?)",
        (event_type, alert_id, datetime.now(timezone.utc).isoformat(), json.dumps(audit_details))
    )
def sanitize_payload(data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        sanitized_payload = validate_payload(data)
        severity = calculate_severity(data)
        alert_record = build_alert_record(sanitized_payload, severity)
        return alert_record, None
    except Exception as e:
        return None, str(e)


def validate_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {k: data.get(k) for k in ALLOWED_PAYLOAD_KEYS if k in data}


def calculate_severity(data: dict[str, Any]) -> int:
    raw_level = int(data.get("rule", {}).get("level", 3))
    return max(0, min(5, raw_level))


def build_alert_record(sanitized_payload: dict[str, Any], severity: int) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "severity": severity,
        "payload": sanitized_payload,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
def parse_and_validate(raw_payload: str) -> dict[str, Any]:
    """Parse and validate a raw JSON payload string.

    Args:
        raw_payload: Raw JSON string containing alert data.

    Returns:
        Sanitized dictionary with validated alert fields.

    Raises:
        RuntimeError: If JSON parsing fails or payload sanitization fails.
    """
    try:
        data = json.loads(raw_payload)
    except json.JSONDecodeError:
        raise RuntimeError("Library code called exit(2)")
    
    sanitized, err = sanitize_payload(data)
    if err:
        logging.error(f"Sanitization failed: {err}")
        raise RuntimeError("Library code called exit(1)")
    
    return sanitized
def persist_alert(conn: sqlite3.Connection, alert_record: dict[str, Any]) -> None:
    payload_json = json.dumps(alert_record['payload'])
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(triage_queue)")
    }

    has_priority = "priority" in columns
    has_payload_ref = "payload_ref" in columns

    if has_priority != has_payload_ref:
        raise RuntimeError(
            "Unsupported partial triage_queue migration: "
            "priority and payload_ref must be added together"
        )

    cursor = conn.cursor()

    if has_priority and has_payload_ref:
        cursor.execute("""
            INSERT INTO triage_queue (
                id,
                severity,
                payload,
                status,
                created_at,
                attempts,
                priority,
                payload_ref
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """, (
            alert_record['id'],
            alert_record['severity'],
            payload_json,
            STATUS_PENDING,
            alert_record['timestamp'],
            severity_to_priority(alert_record['severity']),
            payload_json,
        ))
        return

    # Preserve the current six-column producer contract before migration.
    cursor.execute("""
        INSERT INTO triage_queue (
            id, severity, payload, status, created_at, attempts
        ) VALUES (?, ?, ?, ?, ?, 0)
    """, (
        alert_record['id'],
        alert_record['severity'],
        payload_json,
        STATUS_PENDING,
        alert_record['timestamp']
    ))

def audit_alert(conn: sqlite3.Connection, alert_id: str, details: dict[str, Any]) -> None:
    _audit_log(conn, 'intake', alert_id, details)

def intake_adapter(raw_payload: str) -> int:
    alert_record = parse_and_validate(raw_payload)
    conn = _get_connection()
    try:
        persist_alert(conn, alert_record)
        audit_alert(conn, alert_record['id'], {
            'severity': alert_record['severity'],
            'payload': alert_record['payload'],
            'status': STATUS_PENDING
        })
        conn.commit()
        return 202
    except sqlite3.Error as e:
        logging.critical(f"Database error: {e}")
        raise RuntimeError("Library code called exit(1)")
    finally:
        conn.close()
if __name__ == "__main__":
    import sys
    _load_config()
    try:
        input_data = sys.stdin.read()
        status_code = intake_adapter(input_data)
        sys.exit(0)
    except RuntimeError as e:
        if "exit(2)" in str(e):
            sys.exit(EXIT_PARSE_ERROR)
        sys.exit(EXIT_GENERAL_ERROR)
    except json.JSONDecodeError:
        sys.exit(EXIT_PARSE_ERROR)
    except Exception:
        sys.exit(EXIT_GENERAL_ERROR)