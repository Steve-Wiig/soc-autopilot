import os

# 1. Create contracts/incident_context.py
os.makedirs("contracts", exist_ok=True)
with open("contracts/incident_context.py", "w") as f:
    f.write('''from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from engine.canonical_envelope import EventEnvelope

class EnrichmentProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str
    query_indicator: str
    status: str
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    error_info: Optional[str] = None

class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    indicator: str
    field: str
    value: str
    timestamp: datetime
    trust_class: str  # SYSTEM, UNTRUSTED_EXTERNAL

class StructuredEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    indicator: str
    indicator_type: str
    records: List[EvidenceRecord] = Field(default_factory=list)
    provenance: EnrichmentProvenance

class IncidentEntities(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    users: List[str] = Field(default_factory=list)
    hosts: List[str] = Field(default_factory=list)
    ips: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    hashes: List[str] = Field(default_factory=list)

class IncidentContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    incident_id: UUID = Field(default_factory=uuid4)
    first_seen: datetime
    last_seen: datetime
    alerts: List[EventEnvelope]
    entities: IncidentEntities
    timeline: List[Dict[str, Any]]
    enrichment: List[StructuredEnrichment] = Field(default_factory=list)
    history: List[str] = Field(default_factory=list)
    model_context: str = ""
    correlation_reasons: List[str] = Field(default_factory=list)
''')

# 2. Create engine/correlation_engine.py
os.makedirs("engine", exist_ok=True)
with open("engine/correlation_engine.py", "w") as f:
    f.write('''from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Set, Optional, Tuple
from uuid import UUID, uuid4
from contracts.incident_context import IncidentContext, IncidentEntities
from engine.canonical_envelope import EventEnvelope

logger = logging.getLogger(__name__)

MAX_TIME_WINDOW_MINUTES = 60
MAX_INCIDENT_SIZE = 50
EXPIRATION_MINUTES = 120

class CorrelationState:
    def __init__(self):
        self.incidents: Dict[UUID, List[str]] = {}
        self.event_to_incident: Dict[str, UUID] = {}
        self.events: Dict[str, EventEnvelope] = {}
        self.incident_first_seen: Dict[UUID, datetime] = {}
        self.incident_entities: Dict[UUID, IncidentEntities] = {}
        self.incident_reasons: Dict[UUID, List[str]] = {}

    def _extract_entities(self, envelope: EventEnvelope) -> IncidentEntities:
        payload = envelope.payload or {}
        return IncidentEntities(
            ips=[p for p in [payload.get("src_ip"), payload.get("dst_ip")] if p],
            hosts=[payload.get("hostname")] if payload.get("hostname") else [],
            users=[payload.get("user")] if payload.get("user") else [],
            domains=[payload.get("domain")] if payload.get("domain") else [],
            hashes=[payload.get("hash")] if payload.get("hash") else []
        )

    def _has_entity_overlap(self, e1: IncidentEntities, e2: IncidentEntities) -> bool:
        for field in ["ips", "hosts", "users", "domains", "hashes"]:
            set1 = set(getattr(e1, field))
            set2 = set(getattr(e2, field))
            if set1 and set2 and (set1 & set2):
                return True
        return False

    def _merge_entities(self, e1: IncidentEntities, e2: IncidentEntities) -> IncidentEntities:
        merged = IncidentEntities()
        for field in ["ips", "hosts", "users", "domains", "hashes"]:
            combined = list(set(getattr(e1, field) + getattr(e2, field)))
            setattr(merged, field, combined)
        return merged

    def add_events(self, new_events: List[EventEnvelope]) -> List[IncidentContext]:
        now = datetime.now(timezone.utc)
        expired_incidents = []
        for inc_id, first_seen in self.incident_first_seen.items():
            if (now - first_seen).total_seconds() > (EXPIRATION_MINUTES * 60):
                expired_incidents.append(inc_id)
        
        for inc_id in expired_incidents:
            for eid in self.incidents[inc_id]:
                if eid in self.event_to_incident: del self.event_to_incident[eid]
                if eid in self.events: del self.events[eid]
            del self.incidents[inc_id]
            del self.incident_first_seen[inc_id]
            del self.incident_entities[inc_id]
            del self.incident_reasons[inc_id]

        for event in new_events:
            eid = str(event.event_id)
            if eid in self.event_to_incident: continue
            
            new_entities = self._extract_entities(event)
            self.events[eid] = event
            
            overlapping_incidents = set()
            for inc_id, inc_entities in self.incident_entities.items():
                if self._has_entity_overlap(new_entities, inc_entities):
                    first_seen = self.incident_first_seen[inc_id]
                    if (event.received_at - first_seen).total_seconds() <= (MAX_TIME_WINDOW_MINUTES * 60):
                        if len(self.incidents[inc_id]) < MAX_INCIDENT_SIZE:
                            overlapping_incidents.add(inc_id)

            if not overlapping_incidents:
                new_inc_id = uuid4()
                self.incidents[new_inc_id] = [eid]
                self.event_to_incident[eid] = new_inc_id
                self.incident_first_seen[new_inc_id] = event.received_at
                self.incident_entities[new_inc_id] = new_entities
                self.incident_reasons[new_inc_id] = [f"New incident created for alert {eid}"]
            else:
                target_inc_id = sorted(list(overlapping_incidents))[0]
                for other_inc_id in overlapping_incidents:
                    if other_inc_id != target_inc_id:
                        self.incident_entities[target_inc_id] = self._merge_entities(
                            self.incident_entities[target_inc_id], self.incident_entities[other_inc_id]
                        )
                        for eid_to_move in self.incidents[other_inc_id]:
                            if eid_to_move not in self.incidents[target_inc_id]:
                                self.incidents[target_inc_id].append(eid_to_move)
                                self.event_to_incident[eid_to_move] = target_inc_id
                                self.incident_reasons[target_inc_id].append(f"Merged incident {other_inc_id} into {target_inc_id}")
                        del self.incidents[other_inc_id]
                        del self.incident_first_seen[other_inc_id]
                        del self.incident_entities[other_inc_id]
                        del self.incident_reasons[other_inc_id]

                self.incidents[target_inc_id].append(eid)
                self.event_to_incident[eid] = target_inc_id
                self.incident_entities[target_inc_id] = self._merge_entities(self.incident_entities[target_inc_id], new_entities)
                self.incident_reasons[target_inc_id].append(f"Alert {eid} correlated via entity overlap")

        results = []
        for inc_id, event_ids in self.incidents.items():
            events = [self.events[eid] for eid in event_ids if eid in self.events]
            if not events: continue
            
            entities = self.incident_entities[inc_id]
            timeline = sorted(
                [{"event_id": str(e.event_id), "timestamp": e.received_at.isoformat()} for e in events],
                key=lambda x: x["timestamp"]
            )
            
            alert_types = [e.payload.get("rule", {}).get("description", "Unknown") for e in events if e.payload]
            safe_model_context = (
                f"Incident {inc_id} contains {len(events)} alerts. "
                f"Alert types: {\', \'.join(set(alert_types))}. "
                f"Entities: {len(entities.ips)} IPs, {len(entities.hosts)} hosts, {len(entities.users)} users."
            )

            ctx = IncidentContext(
                incident_id=inc_id,
                first_seen=min(e.received_at for e in events),
                last_seen=max(e.received_at for e in events),
                alerts=events,
                entities=entities,
                timeline=timeline,
                model_context=safe_model_context,
                correlation_reasons=self.incident_reasons[inc_id]
            )
            results.append(ctx)
        return results
''')

# 3. Create tests/test_correlation_streaming.py
os.makedirs("tests", exist_ok=True)
with open("tests/test_correlation_streaming.py", "w") as f:
    f.write('''import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from engine.canonical_envelope import EventEnvelope, TrustLabels
from engine.correlation_engine import CorrelationState

def _make_envelope(src_ip="192.168.1.100", rule_id="500", timestamp=None, event_id=None) -> EventEnvelope:
    if not timestamp: timestamp = datetime.now(timezone.utc)
    if not event_id: event_id = uuid4()
    return EventEnvelope(
        source="wazuh", collector_version="1.0", transform_version="1.0",
        original_payload_hash="abc", normalized_payload_hash="def",
        trust_labels=TrustLabels(),
        payload={"rule": {"id": rule_id, "description": "Suspicious Activity"}, "src_ip": src_ip, "dst_ip": "10.0.0.1", "hostname": "workstation-1"},
        received_at=timestamp, event_id=event_id
    )

def test_transitive_correlation():
    state = CorrelationState()
    t1 = datetime.now(timezone.utc)
    env_a = _make_envelope(src_ip="1.1.1.1", timestamp=t1)
    env_b = _make_envelope(src_ip="1.1.1.1", timestamp=t1 + timedelta(seconds=10))
    env_b.payload["src_ip"] = "2.2.2.2" 
    env_c = _make_envelope(src_ip="2.2.2.2", timestamp=t1 + timedelta(seconds=20))
    
    state.add_events([env_a])
    state.add_events([env_b])
    state.add_events([env_c])
    incidents = state.add_events([])
    assert len(incidents) == 1
    assert len(incidents[0].alerts) == 3

def test_out_of_order_alerts():
    state = CorrelationState()
    t1 = datetime.now(timezone.utc)
    env_c = _make_envelope(src_ip="3.3.3.3", timestamp=t1 + timedelta(minutes=5))
    env_a = _make_envelope(src_ip="3.3.3.3", timestamp=t1)
    state.add_events([env_c])
    state.add_events([env_a])
    incidents = state.add_events([])
    assert len(incidents) == 1
    assert len(incidents[0].alerts) == 2

def test_expired_incidents():
    state = CorrelationState()
    t1 = datetime.now(timezone.utc) - timedelta(hours=3)
    env_old = _make_envelope(src_ip="4.4.4.4", timestamp=t1)
    state.add_events([env_old])
    incidents = state.add_events([])
    assert len(incidents) == 0

def test_max_incident_size():
    state = CorrelationState()
    t1 = datetime.now(timezone.utc)
    events = [_make_envelope(src_ip="5.5.5.5", timestamp=t1 + timedelta(seconds=i)) for i in range(55)]
    state.add_events(events)
    incidents = state.add_events([])
    assert len(incidents) == 1
    assert len(incidents[0].alerts) == 50

def test_unrelated_alerts():
    state = CorrelationState()
    t1 = datetime.now(timezone.utc)
    env_a = _make_envelope(src_ip="6.6.6.6", timestamp=t1)
    env_b = _make_envelope(src_ip="7.7.7.7", timestamp=t1)
    state.add_events([env_a, env_b])
    incidents = state.add_events([])
    assert len(incidents) == 2
''')

print("✅ Step 1 files created successfully.")
print("Run: pytest tests/test_correlation_streaming.py -v")
