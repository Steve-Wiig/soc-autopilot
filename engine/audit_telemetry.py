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
        self._mock_storage = []

    def log_mandatory_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not event_type or not payload:
            raise MandatoryTelemetryFailure("Event type and payload are required")
        
        # Enforce stable identifiers (timestamp is added by the writer, not required in payload)
        required_fields = ["incident_id"]
        for field in required_fields:
            if field not in payload:
                raise MandatoryTelemetryFailure(f"Missing required field: {field}")

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **payload
        }

        try:
            if payload.get("_simulate_telemetry_failure"):
                raise IOError("Simulated telemetry write failure")
            
            self._mock_storage.append(record)
            json.dumps(record)
        except (IOError, TypeError, ValueError) as e:
            logger.error(f"Mandatory telemetry write failed: {e}")
            raise MandatoryTelemetryFailure(f"Telemetry write failed: {e}")
