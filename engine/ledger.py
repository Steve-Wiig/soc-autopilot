"""Ledger event model and parsing utilities.

This module defines the append-only ledger event schema used to record
the lifecycle of a proposal as it moves through observation, evaluation,
proposal, validation, and promotion stages.

Events are serialized as single-line JSON (JSONL) records. Because the
ledger is treated as an evidence trail, parsing is intentionally strict:
malformed, ambiguous, or future-incompatible records are rejected rather
than silently accepted or coerced.
"""

import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

#: Current schema version emitted by this codebase. Existing ledger
#: readers must be able to reject versions newer than this value.
SCHEMA_VERSION: int = 2

#: Top-level fields that are part of the fixed ledger event envelope
#: (as opposed to event-specific payload data). Used when separating
#: envelope fields from payload fields during parsing.
_ENVELOPE_FIELD_NAMES = ("id", "type", "timestamp", "schema_version")


class LedgerEventType(Enum):
    """Explicit lifecycle states for the ledger."""

    OBSERVATION = "OBSERVATION"
    EVALUATION = "EVALUATION"
    PROPOSAL = "PROPOSAL"
    VALIDATION = "VALIDATION"
    PROMOTION = "PROMOTION"


@dataclass
class LedgerEvent:
    """A single, immutable record in the append-only ledger.

    Attributes:
        type: The lifecycle stage this event represents.
        schema_version: Schema version this event was created under.
            New events must always be created at ``SCHEMA_VERSION``.
        timestamp: ISO-8601 UTC timestamp of when the event occurred.
        id: Unique identifier for this event.
        payload: Event-specific data that is not part of the fixed
            envelope (type/timestamp/id/schema_version).
    """

    type: LedgerEventType
    schema_version: int = SCHEMA_VERSION
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate invariants that must hold for any newly created event."""
        if not isinstance(self.type, LedgerEventType):
            raise ValueError("type must be a valid LedgerEventType")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema version for new events: {self.schema_version}")

    def to_dict(self) -> Dict[str, Any]:
        """Return a flat dict representation matching the canonical ledger schema.

        The fixed envelope fields (id, type, timestamp, schema_version) are
        combined with the event's payload fields at the same top level.
        """
        event_dict: Dict[str, Any] = {
            "id": self.id,
            "type": self.type.value,
            "timestamp": self.timestamp,
            "schema_version": self.schema_version,
        }
        # Merge payload into top level to match canonical schema definitions
        event_dict.update(self.payload)
        return event_dict

    def to_json(self) -> str:
        """Serialize this event to a single-line JSON string."""
        return json.dumps(self.to_dict())


def parse_ledger_event(json_str: str) -> LedgerEvent:
    """Safely parse a JSONL line into a LedgerEvent, rejecting corruption.

    Args:
        json_str: A single JSON object as a string, typically one line
            from a ledger JSONL file.

    Returns:
        The parsed LedgerEvent.

    Raises:
        ValueError: If the input is not valid JSON, is not a JSON object,
            is missing required fields, has an unknown event type, has an
            unsupported (future) schema version, or fails lifecycle-specific
            invariants (e.g. a PROMOTION event missing its 'state' field).
    """
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

    payload = {key: value for key, value in data.items() if key not in _ENVELOPE_FIELD_NAMES}

    return LedgerEvent(
        type=event_type,
        id=data.get("id", str(uuid.uuid4())),
        timestamp=timestamp,
        schema_version=schema_version,
        payload=payload,
    )
