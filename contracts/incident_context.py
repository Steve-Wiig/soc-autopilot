from __future__ import annotations
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
