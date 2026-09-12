#!/usr/bin/env python3
"""Pi critic ingestor. Consumes Redis queue, appends to improvement ledger."""
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
import redis

LEDGER_PATH = Path.home() / "Documents/soc-autopilot/overnight/improvement_ledger.jsonl"
QUEUE_NAME = "pi_critic_results"
BLOCK_TIMEOUT_SEC = 5


def _require_redis_password():
    pwd = os.environ.get("REDIS_PASSWORD")
    if not pwd or pwd == "CHANGE_ME":
        raise RuntimeError("Fatal: REDIS_PASSWORD must be explicitly configured")
    return pwd


def _coerce_timestamp(ts):
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    if isinstance(ts, str) and ts:
        return ts
    return datetime.now(tz=timezone.utc).isoformat()


def _build_entry(data):
    ledger_event_id = data.get("ledger_event_id")
    if not ledger_event_id:
        raise ValueError("Missing canonical ledger identity")
    verdict = data.get("verdict") or {}
    status = "PI_APPROVED" if verdict.get("approved") else "PI_REJECTED"
    return {
        "ledger_event_id": ledger_event_id,
        "timestamp": _coerce_timestamp(data.get("timestamp")),
        "file": data.get("file", "unknown"),
        "job_id": data.get("job_id", "unknown"),
        "status": status,
        "reason": verdict.get("reason", "No reason provided"),
        "inference_duration_sec": data.get("inference_duration_sec", 0),
        "source": "pi_critic",
    }


def _append_ledger(entry):
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def main():
    print("Starting pi_redis_ingestor...", flush=True)
    try:
        pwd = _require_redis_password()
    except RuntimeError as e:
        print(f"Fatal Ingestor Error: {e}", file=sys.stderr, flush=True)
        return 1
    try:
        r = redis.Redis(password=pwd, host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()
    except redis.ConnectionError as e:
        print(f"Failed to connect to Redis: {e}", file=sys.stderr, flush=True)
        return 1
    print("Connected to Redis", flush=True)
    while True:
        try:
            result = r.brpop(QUEUE_NAME, timeout=BLOCK_TIMEOUT_SEC)
            if not result:
                continue
            _, item_str = result
            data = json.loads(item_str)
            entry = _build_entry(data)
            _append_ledger(entry)
            print(f"Ingested: {entry['job_id']} ({entry['status']} in {entry['inference_duration_sec']}s)", flush=True)
        except json.JSONDecodeError as e:
            print(f"JSON Decode Error: {e}", flush=True)
        except ValueError as e:
            print(f"Rejected message: {e}", flush=True)
        except Exception as e:
            print(f"Ingestor Loop Error: {e}", flush=True)
            time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
