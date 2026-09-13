"""
engine/reasoning_ledger.py
--------------------------
The Black Box Flight Recorder. Records every LLM prompt and raw response.
Writes to local buffer only. NAS was intentionally removed in P1-4.
"""
import json
import time
import os
import hashlib
from pathlib import Path

ROOT = Path(__file__).parent.parent
BUFFER_DIR = ROOT / "overnight" / ".reasoning_buffer"

def record_interaction(stage: str, prompt: str, raw_response: str, model: str = "unknown"):
    """Appends an LLM interaction to the flight recorder."""
    BUFFER_DIR.mkdir(parents=True, exist_ok=True)
    local_file = BUFFER_DIR / "current.jsonl"
    
    debug_preview = os.getenv(
        "SOC_REASONING_DEBUG",
        "false"
    ).lower() == "true"

    event = {
        "ts": time.time(),
        "stage": stage,
        "model": model,
        "prompt_chars": len(prompt),
        "response_chars": len(raw_response) if raw_response else 0,

        # Privacy-preserving identifiers
        "prompt_hash": hashlib.sha256(
            prompt.encode("utf-8")
        ).hexdigest(),

        "response_hash": hashlib.sha256(
            (raw_response or "").encode("utf-8")
        ).hexdigest(),
    }

    # Explicit operator opt-in only.
    # Disabled by default to prevent accidental leakage.
    if debug_preview:
        event["prompt_preview"] = (
            prompt[:500] + "..."
            if len(prompt) > 500
            else prompt
        )

        event["response_preview"] = (
            raw_response[:500] + "..."
            if raw_response and len(raw_response) > 500
            else raw_response
        )
    
    # 1. Write to local buffer only (NAS was intentionally removed in P1-4)
    try:
        with open(local_file, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        # HARDENED: Fail closed with telemetry
        import logging
        logging.error(f'CONTROL-PLANE FAILURE in reasoning_ledger.py: {e}')
        raise


# --- Telemetry Truth Model ---
from dataclasses import dataclass

@dataclass
class CanonicalTelemetryEvent:
    """Single source of truth for all telemetry. Everything references this."""
    ledger_event_id: str
    event_type: str
    timestamp: str
    payload: dict

    def __post_init__(self):
        if not self.ledger_event_id:
            raise ValueError("ledger_event_id is required for canonical truth.")


# --- PHASE 3 FIX: ENFORCED STATE MACHINE ---
ALLOWED_TRANSITIONS = {
    "OBSERVED": ["PROPOSED"],
    "PROPOSED": ["VALIDATING"],
    "VALIDATING": ["SHADOW_RUNNING"],
    "SHADOW_RUNNING": ["TESTING"],
    "TESTING": ["AWAITING_APPROVAL"],
    "AWAITING_APPROVAL": ["MERGED", "REJECTED"],
    "MERGED": ["APPLIED"],
    "REJECTED": ["ARCHIVED"],
    "APPLIED": [],
    "ARCHIVED": []
}

def transition_state(current_state: str, target_state: str) -> str:
    """Strictly enforces ALLOWED_TRANSITIONS. Raises ValueError on invalid transitions."""
    if target_state not in ALLOWED_TRANSITIONS.get(current_state, []):
        raise ValueError(f"Invalid state transition: {current_state} -> {target_state}")
    return target_state
# ----------------------------------------
