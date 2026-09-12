import redis
import json
from pathlib import Path
from datetime import datetime
import time

LEDGER_PATH = Path.home() / "Documents/soc-autopilot/overnight/improvement_ledger.jsonl"
LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)

print("Starting pi_redis_ingestor...")

try:
    r = redis.Redis(password=os.environ.get("REDIS_PASSWORD", "CHANGE_ME"), host="localhost", port=6379, db=0, decode_responses=True)
    print("✅ Connected to Redis")

    while True:
        try:
            result = r.brpop("pi_critic_results", timeout=5)
            if not result:
                continue
            
            queue_name, item_str = result
            data = json.loads(item_str)
            
            job_id = data.get("job_id", "unknown")
            verdict = data.get("verdict", {})
            duration = data.get("inference_duration_sec", 0)
            
            # Extract approval status and reason from the nested verdict dict
            is_approved = verdict.get("approved", False)
            reason = verdict.get("reason", "No reason provided")
            
            status = "PI_APPROVED" if is_approved else "PI_REJECTED"

            ts = data.get("timestamp")
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(ts).isoformat()
            elif not ts:
                ts = datetime.now().isoformat()

            entry = {
                "timestamp": ts,
                "file": data.get("file", "unknown"),
                "job_id": job_id,
                "status": status,
                "reason": reason,
                "inference_duration_sec": duration,
                "source": "pi_critic"
            }
            
            with open(LEDGER_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
            
            print(f"✅ Ingested: {job_id} ({status} in {duration}s)")

        except json.JSONDecodeError as e:
            print(f"❌ JSON Decode Error: {e}")
        except Exception as e:
            print(f"❌ Ingestor Loop Error: {e}")
            time.sleep(1)

except redis.ConnectionError as e:
    print(f"❌ Failed to connect to Redis: {e}")
except Exception as e:
    print(f"❌ Fatal Ingestor Error: {e}")
