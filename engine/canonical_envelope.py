"""
soc.event.envelope.v1
Strict canonical envelope for all SOC intake.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class TrustLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sanitized: bool = False
    untrusted_content: bool = True
    provenance_verified: bool = False


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: UUID = Field(default_factory=uuid4)
    source: Literal["wazuh", "eve", "unknown"]
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    schema_version: Literal["1.0"] = "1.0"
    collector_version: str
    transform_version: str

    original_payload_hash: str
    normalized_payload_hash: str

    trust_labels: TrustLabels = Field(default_factory=TrustLabels)

    # Strictly sanitized payload. No arbitrary nested execution.
    payload: Dict[str, Any]
