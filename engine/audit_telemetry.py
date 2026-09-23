"""
soc.engine.audit_telemetry.v1
Mandatory audit telemetry. If a critical security-decision event cannot be recorded,
the system must fail closed.
"""
from __future__ import annotations
import logging
import json
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

class MandatoryTelemetryFailure(Exception):
    """Raised when a mandatory audit event cannot be written."""
    pass

class AuditTelemetryWriter:
    def __init__(self):
        # In production, this would be a secure append-only log or DB
        self._mock_storage = []

    def log_mandatory_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """
        Log a mandatory security-decision event.
        Raises MandatoryTelemetryFailure if the write fails.
        """
        if not event_type or not payload:
            raise MandatoryTelemetryFailure("Event type and payload are required")
        
        # Enforce stable identifiers
        required_fields = ["incident_id", "event_type", "timestamp"]
        for field in required_fields:
            if field not in payload:
                raise MandatoryTelemetryFailure(f"Missing required field: {field}")

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **payload
        }

        try:
            # Simulate write. In production, this is a DB/secure log write.
            # We simulate a failure if a specific mock flag is set in the payload
            if payload.get("_simulate_telemetry_failure"):
                raise IOError("Simulated telemetry write failure")
            
            self._mock_storage.append(record)
            # Ensure it's serializable (catches unserializable objects early)
            json.dumps(record)
        except (IOError, TypeError, ValueError) as e:
            logger.error(f"Mandatory telemetry write failed: {e}")
            raise MandatoryTelemetryFailure(f"Telemetry write failed: {e}")
