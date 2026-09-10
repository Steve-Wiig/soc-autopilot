"""
Crushes identical alerts into a single investigation cluster.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

from engine.canonical_envelope import EventEnvelope

class AlertCluster(BaseModel):
    cluster_id: UUID = Field(default_factory=uuid4)
    signature_hash: str
    event_count: int
    first_seen: str
    last_seen: str
    representative_event_id: UUID
    representative_payload: Dict[str, Any] = Field(default_factory=dict)
    events: List[UUID]

def generate_alert_signature(envelope: EventEnvelope) -> str:
    payload = envelope.payload
    signature_data = {
        "source": envelope.source,
        "rule_id": payload.get("rule", {}).get("id") or payload.get("rule_id", "unknown"),
        "src_ip": payload.get("src_ip") or payload.get("source", {}).get("ip", "unknown"),
        "dest_ip": payload.get("dest_ip") or payload.get("destination", {}).get("ip", "unknown"),
        "action": payload.get("action", "unknown"),
    }
    raw_sig = json.dumps(signature_data, sort_keys=True)
    return hashlib.sha256(raw_sig.encode()).hexdigest()

def cluster_alerts(envelopes: List[EventEnvelope]) -> List[AlertCluster]:
    clusters_map: Dict[str, AlertCluster] = {}

    for env in envelopes:
        sig = generate_alert_signature(env)

        if sig not in clusters_map:
            clusters_map[sig] = AlertCluster(
                signature_hash=sig,
                event_count=1,
                first_seen=env.received_at.isoformat(),
                last_seen=env.received_at.isoformat(),
                representative_event_id=env.event_id,
                representative_payload=env.payload,
                events=[env.event_id]
            )
        else:
            cluster = clusters_map[sig]
            cluster.event_count += 1
            cluster.last_seen = env.received_at.isoformat()
            cluster.events.append(env.event_id)

    return list(clusters_map.values())
