import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any

SCHEMA_VERSION = 2

class LedgerEventType(Enum):
    """Explicit lifecycle states for the ledger."""
    OBSERVATION = "OBSERVATION"
    EVALUATION = "EVALUATION"
    PROPOSAL = "PROPOSAL"
    VALIDATION = "VALIDATION"
    PROMOTION = "PROMOTION"

@dataclass
class LedgerEvent:
    type: LedgerEventType
    schema_version: int = SCHEMA_VERSION
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.type, LedgerEventType):
            raise ValueError("type must be a valid LedgerEventType")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema version for new events: {self.schema_version}")

    def to_dict(self) -> Dict[str, Any]:
        base = {
            "id": self.id,
            "type": self.type.value,
            "timestamp": self.timestamp,
            "schema_version": self.schema_version
        }
        # Merge payload into top level to match canonical schema definitions
        base.update(self.payload)
        return base

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

def parse_ledger_event(json_str: str) -> LedgerEvent:
    """Safely parses a JSONL line into a LedgerEvent, rejecting corruption."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON")

    if not isinstance(data, dict):
        raise ValueError("Event must be a JSON object")

    event_type_str = data.get("type")
    if not event_type_str:
        raise ValueError("Missing 'type' field")

    try:
        event_type = LedgerEventType(event_type_str)
    except ValueError:
        raise ValueError(f"Unknown event type: {event_type_str}")

    schema_version = data.get("schema_version", 1)

    # Safely reject future, incompatible schemas
    if schema_version > SCHEMA_VERSION:
        raise ValueError(f"Unsupported future schema version: {schema_version}")

    # Strict validation for specific lifecycle invariants
    if event_type == LedgerEventType.PROMOTION and "state" not in data:
        raise ValueError("Promotion event missing required 'state' field")

    # Ledger entries are evidence records. Missing or blank timestamps
    # must fail closed rather than silently becoming non-auditable data.
    timestamp = data.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("Missing timestamp field")

    payload = {k: v for k, v in data.items() if k not in ["id", "type", "timestamp", "schema_version"]}

    return LedgerEvent(
        type=event_type,
        id=data.get("id", str(uuid.uuid4())),
        timestamp=timestamp,
        schema_version=schema_version,
        payload=payload
    )
