import redis, json, os
from pathlib import Path
from datetime import datetime

try:
    r = redis.Redis(host="192.168.1.31", port=6379, db=0, decode_responses=True, socket_connect_timeout=2)
    ledger_path = Path.home() / "Documents/soc-autopilot/overnight/improvement_ledger.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    
    while True:
        item = r.rpop("pi_critic_results")
        if not item: break
        data = json.loads(item)
        verdict = data.get("verdict", {})
        
        ts = data.get("timestamp")
        if isinstance(ts, float):
            ts = datetime.fromtimestamp(ts).isoformat()

        entry = {
            "timestamp": ts,
            "file": data.get("file"),
            "job_id": data.get("job_id"),
            "status": "APPLIED" if verdict.get("approved") else "REJECTED",
            "reason": verdict.get("reason", "No reason"),
            "source": "pi_critic"
        }
        with open(ledger_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
except Exception:
    pass
