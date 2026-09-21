"""
engine/reasoning_ledger.py
--------------------------
The Black Box Flight Recorder. Records every LLM prompt and raw response.
Writes to local buffer only. NAS was intentionally removed in P1-4.
"""
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).parent.parent
BUFFER_DIR = ROOT / "overnight" / ".reasoning_buffer"

logger = logging.getLogger(__name__)

# Maximum number of characters to retain when generating debug previews.
_DEBUG_PREVIEW_MAX_CHARS = 500


def record_interaction(
    stage: str,
    prompt: str,
    raw_response: str,
    model: str = "unknown",
) -> None:
    """Appends a single LLM interaction to the flight recorder.

    Writes a JSON line describing the interaction to the local buffer file
    (``overnight/.reasoning_buffer/current.jsonl``). Only hashes of the
    prompt/response are stored by default; human-readable previews are only
    included when explicitly enabled via the ``SOC_REASONING_DEBUG``
    environment variable, to avoid accidental data leakage.

    Args:
        stage: Name of the pipeline stage that produced this interaction.
        prompt: The full prompt text sent to the LLM.
        raw_response: The full raw response text returned by the LLM.
        model: Identifier of the model used, if known.

    Raises:
        Exception: Re-raises any exception encountered while writing to the
            local buffer file, after logging it, so callers fail closed
            instead of silently losing telemetry.
    """
    BUFFER_DIR.mkdir(parents=True, exist_ok=True)
    local_file = BUFFER_DIR / "current.jsonl"

    debug_preview_enabled = os.getenv(
        "SOC_REASONING_DEBUG",
        "false",
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
    if debug_preview_enabled:
        event["prompt_preview"] = (
            prompt[:_DEBUG_PREVIEW_MAX_CHARS] + "..."
            if len(prompt) > _DEBUG_PREVIEW_MAX_CHARS
            else prompt
        )

        event["response_preview"] = (
            raw_response[:_DEBUG_PREVIEW_MAX_CHARS] + "..."
            if raw_response and len(raw_response) > _DEBUG_PREVIEW_MAX_CHARS
            else raw_response
        )

    # 1. Write to local buffer only (NAS was intentionally removed in P1-4)
    try:
        with open(local_file, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        # HARDENED: Fail closed with telemetry
        logger.error("CONTROL-PLANE FAILURE in reasoning_ledger.py: %s", e)
        raise


# --- Telemetry Truth Model ---

@dataclass
class CanonicalTelemetryEvent:
    """Single source of truth for all telemetry. Everything references this.

    Attributes:
        ledger_event_id: Unique identifier tying this event back to its
            originating ledger entry. Required and must be non-empty.
        event_type: Category/type of the telemetry event.
        timestamp: ISO-8601 (or equivalent) timestamp string for the event.
        payload: Arbitrary event-specific data.
    """
    ledger_event_id: str
    event_type: str
    timestamp: str
    payload: dict

    def __post_init__(self) -> None:
        if not self.ledger_event_id:
            raise ValueError("ledger_event_id is required for canonical truth.")


# --- PHASE 3 FIX: ENFORCED STATE MACHINE ---
ALLOWED_TRANSITIONS: Dict[str, List[str]] = {
    "OBSERVED": ["PROPOSED"],
    "PROPOSED": ["VALIDATING"],
    "VALIDATING": ["SHADOW_RUNNING"],
    "SHADOW_RUNNING": ["TESTING"],
    "TESTING": ["AWAITING_APPROVAL"],
    "AWAITING_APPROVAL": ["MERGED", "REJECTED"],
    "MERGED": ["APPLIED"],
    "REJECTED": ["ARCHIVED"],
    "APPLIED": [],
    "ARCHIVED": [],
}


def transition_state(current_state: str, target_state: str) -> str:
    """Validates and performs a state transition.

    Strictly enforces :data:`ALLOWED_TRANSITIONS`.

    Args:
        current_state: The state the entity is currently in.
        target_state: The state being transitioned to.

    Returns:
        The ``target_state``, if the transition is allowed.

    Raises:
        ValueError: If ``target_state`` is not a valid transition from
            ``current_state``.
    """
    if target_state not in ALLOWED_TRANSITIONS.get(current_state, []):
        raise ValueError(f"Invalid state transition: {current_state} -> {target_state}")
    return target_state
# ----------------------------------------
