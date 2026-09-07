#!/usr/bin/env python3
import json, shutil, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.telemetry import TelemetryWriter
from engine.telemetry_identity import event_identity

INCOMING_DIR = ROOT / "runtime" / "incoming" / "pi"
PROCESSED_DIR = ROOT / "runtime" / "incoming" / "pi_processed"
QUARANTINE_DIR = ROOT / "runtime" / "incoming" / "pi_quarantine"

writer = TelemetryWriter()

def normalize_pi_event(raw: dict) -> dict:
    return {
        "event_id": raw.get("event_id"),
        "event_type": raw.get("event_type"),
        "node_id": raw.get("source", "raspberry_pi"),
        "source": "pi_edge",
        "provider": raw.get("provider", "local_bandit"),
        "model": raw.get("model", "bandit_pylint"),
        "created_at": raw.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "payload": {k: v for k, v in raw.items() if k not in ["event_type", "source", "timestamp", "event_id"]},
        "signature": raw.get("event_id")
    }

def process_file(filepath: Path):
    temp_path = filepath.with_suffix(".processing")
    shutil.move(str(filepath), str(temp_path))
    accepted, rejected = 0, 0
    
    try:
        with temp_path.open('r') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    raw = json.loads(line)
                    if "event_type" not in raw: raise ValueError("Missing event_type")
                    canonical = normalize_pi_event(raw)
                    writer.log_attempt(canonical)

                    # ALSO write to pending findings file for the bridge timer
                    pending_file = ROOT / "runtime" / "analysis" / "pi_findings_pending.jsonl"
                    pending_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(pending_file, 'a') as pf:
                        pf.write(json.dumps(canonical) + "\n")

                    accepted += 1
                except Exception as e:
                    print(f"Quarantine bad line: {e}")
                    rejected += 1
        
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(PROCESSED_DIR / filepath.name))
        print(f"✅ Ingested {filepath.name}: {accepted} accepted, {rejected} rejected.")
    except Exception as e:
        print(f"❌ Fatal error processing {filepath.name}: {e}")
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(QUARANTINE_DIR / filepath.name))

if __name__ == "__main__":
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    files = list(INCOMING_DIR.glob("*.jsonl"))
    if not files: print("No incoming Pi files."); sys.exit(0)
    for f in files: process_file(f)
