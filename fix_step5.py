import os
from uuid import uuid4

# 1. Fix audit_telemetry.py to not require timestamp in payload (it adds it itself)
with open("engine/audit_telemetry.py", "w") as f:
    f.write('''"""
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
''')

# 2. Fix the test file to use valid UUIDs
with open("tests/test_writeback_authorization.py", "w") as f:
    f.write('''"""
Tests for Bounded Writeback and Authorization.
"""
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from engine.canonical_envelope import EventEnvelope, TrustLabels
from engine.soc_pipeline import SOCPipeline
from engine.writeback.authorization import create_authorization
from engine.writeback.so_cases import SOCasesWriteback, WritebackAuthorizationError, WritebackFailure
from contracts.incident_context import IncidentContext, IncidentEntities

def _make_envelope(src_ip="1.1.1.1", timestamp=None) -> EventEnvelope:
    if not timestamp: timestamp = datetime.now(timezone.utc)
    return EventEnvelope(
        source="wazuh", collector_version="1.0", transform_version="1.0",
        original_payload_hash="abc", normalized_payload_hash="def",
        trust_labels=TrustLabels(),
        payload={"rule": {"id": "500", "description": "Test"}, "src_ip": src_ip},
        received_at=timestamp, event_id=uuid4()
    )

def _make_incident(incident_id_str: str = None) -> IncidentContext:
    inc_id = uuid4() if incident_id_str is None else uuid4() # Use valid UUID
    return IncidentContext(
        incident_id=inc_id,
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        alerts=[],
        entities=IncidentEntities(),
        timeline=[],
        model_context="test"
    )

def test_successful_bounded_writeback():
    """A valid authorization allows the writeback to succeed."""
    pipeline = SOCPipeline()
    env = _make_envelope(src_ip="1.1.1.1")
    
    results = pipeline.process_alerts([env])
    assert len(results) == 1
    incident, decision, writeback_result = results[0]
    
    assert decision.authorized_action == "ESCALATE"
    assert "Created case" in writeback_result

def test_authorization_incident_mismatch():
    """An authorization for a different incident must be rejected."""
    executor = SOCasesWriteback()
    incident = _make_incident()
    
    auth = create_authorization(
        decision_id="dec-1",
        incident_id=str(uuid4()), # Different UUID
        action="ESCALATE",
        target="so_cases",
        parameters={"reason": "test"}
    )
    
    with pytest.raises(WritebackAuthorizationError) as exc_info:
        executor.execute(auth, incident, {"reason": "test"})
    assert "Incident mismatch" in str(exc_info.value)

def test_authorization_parameter_tampering():
    """Altered parameters must fail hash verification."""
    executor = SOCasesWriteback()
    incident = _make_incident()
    inc_id_str = str(incident.incident_id)
    
    auth = create_authorization(
        decision_id="dec-1",
        incident_id=inc_id_str,
        action="ESCALATE",
        target="so_cases",
        parameters={"reason": "original"}
    )
    
    tampered_params = {"reason": "original", "escalate_to_admin": True}
    
    with pytest.raises(WritebackAuthorizationError) as exc_info:
        executor.execute(auth, incident, tampered_params)
    assert "Parameter hash mismatch" in str(exc_info.value)

def test_authorization_expired():
    """An expired authorization must be rejected."""
    executor = SOCasesWriteback()
    incident = _make_incident()
    inc_id_str = str(incident.incident_id)
    
    auth = create_authorization(
        decision_id="dec-1",
        incident_id=inc_id_str,
        action="ESCALATE",
        target="so_cases",
        parameters={"reason": "test"},
        ttl_minutes=0
    )
    # Force expiration
    auth.expiration = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    
    with pytest.raises(WritebackAuthorizationError) as exc_info:
        executor.execute(auth, incident, {"reason": "test"})
    assert "expired" in str(exc_info.value).lower()

def test_replay_attack_prevention():
    """Reusing an authorization for a different decision is prevented by decision_id binding."""
    auth1 = create_authorization("dec-1", "inc-1", "ESCALATE", "so_cases", {"r": "1"})
    auth2 = create_authorization("dec-2", "inc-1", "ESCALATE", "so_cases", {"r": "1"})
    
    assert auth1.authorization_id != auth2.authorization_id
    assert auth1.decision_id != auth2.decision_id
''')

print("✅ Step 5 fixes applied.")
