import sqlite3
import time
import argparse
import json
import logging
import hashlib
import re
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from engine.queue_priority import priority_case_sql
from engine.telemetry import log_attempt
from engine.model_registry import get_default_router
from engine.inference_service import InferenceService
from engine.trust_boundary import fence_payload_for_llm, scan_for_injection
from contracts.slm_recommendation import SLMRawRecommendation, RecommendationEnvelope, EXPECTED_SCHEMA_VERSION

logger = logging.getLogger(__name__)
DEFAULT_PRIORITY = 5

@dataclass
class WorkerConfig:
    db: str
    lease: int
    max_retries: int
    base_delay: float

def _ensure_priority_column(conn: sqlite3.Connection) -> bool:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(triage_queue)")
    columns = {row[1] for row in cursor.fetchall()}
    changed = False
    if "priority" not in columns:
        cursor.execute(f"ALTER TABLE triage_queue ADD COLUMN priority INTEGER NOT NULL DEFAULT {int(DEFAULT_PRIORITY)}")
        changed = True
    worker_columns = {"started_at": "TEXT", "lease_expires_at": "TEXT", "last_heartbeat_at": "TEXT", "payload_ref": "TEXT", "failure_reason": "TEXT"}
    for column, sql_type in worker_columns.items():
        if column not in columns:
            cursor.execute(f"ALTER TABLE triage_queue ADD COLUMN {column} {sql_type}")
            changed = True
    priority_expression = priority_case_sql("severity")
    cursor.execute(f"UPDATE triage_queue SET priority = {priority_expression}")
    cursor.execute("UPDATE triage_queue SET payload_ref = payload WHERE payload_ref IS NULL")
    cursor.execute("CREATE TABLE IF NOT EXISTS verdicts (job_id TEXT NOT NULL, result TEXT NOT NULL, processed_at TEXT NOT NULL)")
    return changed

def _ensure_claim_index(conn: sqlite3.Connection, priority_added: bool) -> None:
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_triage_claim'")
    index_exists = cursor.fetchone() is not None
    if priority_added or not index_exists:
        cursor.execute("DROP INDEX IF EXISTS idx_triage_claim")
        cursor.execute("CREATE INDEX idx_triage_claim ON triage_queue(status, priority, created_at) WHERE status = 'pending'")

def get_db(db_path: str) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        priority_added = _ensure_priority_column(conn)
        _ensure_claim_index(conn, priority_added)
        conn.commit()
        return conn
    except Exception as e:
        logger.error(f"DB_ERROR: {e}")
        raise RuntimeError(f"Failed to connect to database: {e}")

def heartbeat(conn: sqlite3.Connection, job_id: int, lease_interval: int) -> None:
    try:
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(seconds=lease_interval)
        conn.execute("UPDATE triage_queue SET last_heartbeat_at = ?, lease_expires_at = ? WHERE id = ?", (now.strftime('%Y-%m-%d %H:%M:%S'), expiry.strftime('%Y-%m-%d %H:%M:%S'), job_id))
        conn.commit()
    except Exception as e:
        logger.error(f"HEARTBEAT_FAIL: {e}")

def reap_stale(conn: sqlite3.Connection) -> None:
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("UPDATE triage_queue SET status = 'pending', started_at = NULL, lease_expires_at = NULL, last_heartbeat_at = NULL WHERE status = 'processing' AND lease_expires_at < ?", (now_str,))
    conn.commit()

def get_queue_depth(conn):
    row = conn.execute("SELECT COUNT(*) FROM triage_queue WHERE status = 'pending'").fetchone()
    return int(row[0]) if row else 0

LAST_HEARTBEAT = 0
HEARTBEAT_INTERVAL = 60

def emit_heartbeat(conn, status="idle"):
    global LAST_HEARTBEAT
    now = time.time()
    if now - LAST_HEARTBEAT >= HEARTBEAT_INTERVAL:
        log_attempt({"event_type": "pi_heartbeat"}, worker_type="pi", status=status, queue_depth=get_queue_depth(conn))
        LAST_HEARTBEAT = now

def run_worker(config: WorkerConfig) -> None:
    conn = get_db(config.db)
    empty_queue_backoff = 1
    MAX_BACKOFF = 30
    router = get_default_router()
    inference_service = InferenceService(router, hard_timeout_s=30.0)

    while True:
        emit_heartbeat(conn, status="idle")
        reap_stale(conn)
        row = conn.execute(
            "UPDATE triage_queue SET status = 'processing', started_at = ?, attempts = attempts + 1, lease_expires_at = ? WHERE id = (SELECT id FROM triage_queue WHERE status = 'pending' ORDER BY priority ASC, created_at ASC LIMIT 1) RETURNING id, payload_ref",
            (datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), (datetime.now(timezone.utc) + timedelta(seconds=config.lease)).strftime('%Y-%m-%d %H:%M:%S'))
        ).fetchone()
        conn.commit()
        
        if not row:
            time.sleep(empty_queue_backoff)
            empty_queue_backoff = min(empty_queue_backoff * 2, MAX_BACKOFF)
            continue
            
        empty_queue_backoff = 1
        emit_heartbeat(conn, status="active")
        job_id, payload = row['id'], row['payload_ref']
        
        try:
            payload_dict = json.loads(payload) if isinstance(payload, str) else payload
            
            # P0: Prompt Injection Defense
            if scan_for_injection(payload):
                logger.warning(f"Potential prompt injection detected in job {job_id}. Forcing REVIEW.")
                forced_verdict = {"recommendation_id": f"REC-{job_id}-INJECTION", "decision_id": f"DEC-{job_id}-INJECTION", "outcome": "REVIEW", "reason": "Prompt injection pattern detected"}
                conn.execute("INSERT INTO verdicts (job_id, result, processed_at) VALUES (?, ?, ?)",
                    (job_id, json.dumps(forced_verdict), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')))
                conn.execute("UPDATE triage_queue SET status = 'completed' WHERE id = ?", (job_id,))
                conn.commit()
                continue

            # P0: Structured Prompt Fencing (Trust Boundary Enforcement)
            fenced_prompt = fence_payload_for_llm(payload_dict)
            inference_result = inference_service.generate(prompt=fenced_prompt, role="triage", scope="soc")
            raw_output = inference_result.raw_output
            raw_output_hash = hashlib.sha256(raw_output.encode('utf-8')).hexdigest()
            cleaned_output = re.sub(r'^```json\s*', '', raw_output.strip(), flags=re.MULTILINE)
            cleaned_output = re.sub(r'\s*```\s*$', '', cleaned_output, flags=re.MULTILINE)
            
            try:
                raw_rec = SLMRawRecommendation.model_validate_json(cleaned_output)
            except Exception as e:
                logger.error(f"Contract violation for job {job_id}. Hash: {raw_output_hash}. Details: {e}")
                conn.execute("UPDATE triage_queue SET status = 'failed', failure_reason = 'CONTRACT_VIOLATION' WHERE id = ?", (job_id,))
                conn.commit()
                continue

            recommendation_id = f"REC-{job_id}-{inference_result.provider_id}-{raw_output_hash[:8]}"
            envelope = RecommendationEnvelope(
                recommendation_id=recommendation_id, event_id=str(job_id), envelope_schema_version="1.0",
                recommendation_schema_version=EXPECTED_SCHEMA_VERSION, model_id=inference_result.model_id,
                model_version=inference_result.model_version, raw_output_hash=raw_output_hash, recommendation=raw_rec
            )

            decision_outcome = "REVIEW" if raw_rec.requires_human_review else "ALLOW"
            decision_id = f"DEC-{job_id}-{int(time.time())}"

            conn.execute("INSERT INTO verdicts (job_id, result, processed_at) VALUES (?, ?, ?)",
                (job_id, json.dumps({"recommendation_id": recommendation_id, "decision_id": decision_id, "outcome": decision_outcome, "envelope": envelope.model_dump(mode='json')}), datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')))
            conn.execute("UPDATE triage_queue SET status = 'completed' WHERE id = ?", (job_id,))
            conn.commit()

        except RuntimeError as e:
            logger.error(f"All local models failed for job {job_id}: {e}")
            conn.execute("UPDATE triage_queue SET status = 'failed', failure_reason = 'LOCAL_MODEL_UNAVAILABLE' WHERE id = ?", (job_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"Non-retryable error processing job {job_id}: {e}")
            conn.execute("UPDATE triage_queue SET status = 'failed', failure_reason = ? WHERE id = ?", (str(e), job_id))
            conn.commit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--lease", type=int, default=900)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--base-delay", type=float, default=1.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    config = WorkerConfig(db=args.db, lease=args.lease, max_retries=args.max_retries, base_delay=args.base_delay)
    try:
        run_worker(config)
    except KeyboardInterrupt:
        pass
    except Exception:
        raise RuntimeError('Worker failed')
