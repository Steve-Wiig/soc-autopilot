from __future__ import annotations
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
                f"Alert types: {', '.join(set(alert_types))}. "
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
