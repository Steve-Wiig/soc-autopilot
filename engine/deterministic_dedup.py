"""
Deterministic alert deduplication.

Crushes identical alerts into a single investigation cluster based on a
deterministic signature derived from key alert attributes (source, rule,
source/destination IPs, and action).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

from engine.canonical_envelope import EventEnvelope


class AlertCluster(BaseModel):
    """
    Represents a group of alerts that share the same deterministic signature.

    Attributes:
        cluster_id: Unique identifier for this cluster.
        signature_hash: SHA-256 hash used to group matching alerts.
        event_count: Total number of events aggregated into this cluster.
        first_seen: ISO-formatted timestamp of the earliest event in the cluster.
        last_seen: ISO-formatted timestamp of the most recent event in the cluster.
        representative_event_id: Event ID of the first event used to represent the cluster.
        representative_payload: Payload of the representative event.
        events: List of event IDs belonging to this cluster.
    """
    cluster_id: UUID = Field(default_factory=uuid4)
    signature_hash: str
    event_count: int
    first_seen: str
    last_seen: str
    representative_event_id: UUID
    representative_payload: Dict[str, Any] = Field(default_factory=dict)
    events: List[UUID]


def generate_alert_signature(envelope: EventEnvelope) -> str:
    """
    Generate a deterministic SHA-256 signature for an event envelope.

    The signature is derived from a fixed set of fields (source, rule ID,
    source IP, destination IP, and action) so that identical alerts produce
    the same hash regardless of arrival order or minor payload differences.

    Args:
        envelope: The event envelope to generate a signature for.

    Returns:
        A hex-encoded SHA-256 hash string representing the alert signature.
    """
    payload = envelope.payload
    signature_data: Dict[str, Any] = {
        "source": envelope.source,
        "rule_id": payload.get("rule", {}).get("id") or payload.get("rule_id", "unknown"),
        "src_ip": payload.get("src_ip") or payload.get("source", {}).get("ip", "unknown"),
        "dest_ip": payload.get("dest_ip") or payload.get("destination", {}).get("ip", "unknown"),
        "action": payload.get("action", "unknown"),
    }
    raw_signature = json.dumps(signature_data, sort_keys=True)
    return hashlib.sha256(raw_signature.encode()).hexdigest()


def cluster_alerts(envelopes: List[EventEnvelope]) -> List[AlertCluster]:
    """
    Group a list of event envelopes into deduplicated alert clusters.

    Envelopes that share the same deterministic signature (see
    `generate_alert_signature`) are merged into a single `AlertCluster`,
    with the first occurrence acting as the representative event.

    Args:
        envelopes: List of event envelopes to cluster.

    Returns:
        A list of `AlertCluster` instances, one per unique signature.
    """
    signature_to_cluster: Dict[str, AlertCluster] = {}

    for envelope in envelopes:
        signature = generate_alert_signature(envelope)

        if signature not in signature_to_cluster:
            signature_to_cluster[signature] = AlertCluster(
                signature_hash=signature,
                event_count=1,
                first_seen=envelope.received_at.isoformat(),
                last_seen=envelope.received_at.isoformat(),
                representative_event_id=envelope.event_id,
                representative_payload=envelope.payload,
                events=[envelope.event_id]
            )
        else:
            cluster = signature_to_cluster[signature]
            cluster.event_count += 1
            cluster.last_seen = envelope.received_at.isoformat()
            cluster.events.append(envelope.event_id)

    return list(signature_to_cluster.values())
