#!/usr/bin/env python3
"""Ingest Raspberry Pi edge telemetry files into the engine's telemetry store.

This script watches an incoming directory for newline-delimited JSON (.jsonl)
files produced by Raspberry Pi edge nodes, normalizes each event into the
canonical telemetry schema, writes it via TelemetryWriter, and also appends
it to a pending findings file consumed by a separate bridge timer process.

Processed files are moved to a "processed" directory on success, or to a
"quarantine" directory if a fatal error occurs while processing the file.
"""

import json
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.telemetry import TelemetryWriter
from engine.telemetry_identity import event_identity

INCOMING_DIR = ROOT / "runtime" / "incoming" / "pi"
PROCESSED_DIR = ROOT / "runtime" / "incoming" / "pi_processed"
QUARANTINE_DIR = ROOT / "runtime" / "incoming" / "pi_quarantine"
PENDING_FINDINGS_FILE = ROOT / "runtime" / "analysis" / "pi_findings_pending.jsonl"

# Fields already captured explicitly in the canonical event and therefore
# excluded from the generic "payload" bucket.
_EXCLUDED_PAYLOAD_FIELDS = ("event_type", "source", "timestamp", "event_id")


def normalize_pi_event(raw_event: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a raw Pi edge event into the canonical telemetry schema.

    Args:
        raw_event: The raw JSON object parsed from a single line of the
            incoming .jsonl file.

    Returns:
        A dictionary matching the canonical telemetry event shape expected
        by TelemetryWriter.
    """
    return {
        "event_id": raw_event.get("event_id"),
        "event_type": raw_event.get("event_type"),
        "node_id": raw_event.get("source", "raspberry_pi"),
        "source": "pi_edge",
        "provider": raw_event.get("provider", "local_bandit"),
        "model": raw_event.get("model", "bandit_pylint"),
        "created_at": raw_event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "payload": {
            key: value
            for key, value in raw_event.items()
            if key not in _EXCLUDED_PAYLOAD_FIELDS
        },
        "signature": raw_event.get("event_id"),
    }


def process_file(filepath: Path, writer: TelemetryWriter) -> None:
    """Process a single incoming .jsonl file line by line.

    Each valid line is normalized and logged via the given TelemetryWriter,
    then appended to the pending findings file for the bridge timer. On
    success the source file is moved to PROCESSED_DIR; on a fatal error it
    is moved to QUARANTINE_DIR instead.

    Args:
        filepath: Path to the incoming .jsonl file to process.
        writer: The TelemetryWriter used to persist normalized events.
    """
    temp_path = filepath.with_suffix(".processing")
    shutil.move(str(filepath), str(temp_path))
    accepted_count, rejected_count = 0, 0

    try:
        with temp_path.open('r') as line_source:
            for line in line_source:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw_event = json.loads(line)
                    if "event_type" not in raw_event:
                        raise ValueError("Missing event_type")

                    canonical_event = normalize_pi_event(raw_event)
                    writer.log_attempt(canonical_event)

                    # Also write to pending findings file for the bridge timer.
                    PENDING_FINDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(PENDING_FINDINGS_FILE, 'a') as pending_handle:
                        pending_handle.write(json.dumps(canonical_event) + "\n")

                    accepted_count += 1
                except Exception as exc:
                    print(f"Quarantine bad line: {exc}")
                    rejected_count += 1

        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(PROCESSED_DIR / filepath.name))
        print(f"✅ Ingested {filepath.name}: {accepted_count} accepted, {rejected_count} rejected.")
    except Exception as exc:
        print(f"❌ Fatal error processing {filepath.name}: {exc}")
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), str(QUARANTINE_DIR / filepath.name))


def main() -> None:
    """Entry point: find and process all incoming Pi .jsonl files."""
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    incoming_files = list(INCOMING_DIR.glob("*.jsonl"))

    if not incoming_files:
        print("No incoming Pi files.")
        sys.exit(0)

    writer = TelemetryWriter()
    for filepath in incoming_files:
        process_file(filepath, writer)


if __name__ == "__main__":
    main()
