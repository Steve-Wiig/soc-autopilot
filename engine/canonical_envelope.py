"""
soc.event.envelope.v1

Strict canonical envelope for all SOC intake.

This module defines the canonical data contract that every ingested
security event (e.g., from Wazuh, Suricata/EVE, etc.) must conform to
before it is allowed further into the pipeline. The envelope enforces
strict schema validation (no unknown fields) and carries provenance /
trust metadata alongside the sanitized event payload.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class TrustLabels(BaseModel):
    """Provenance and trust metadata attached to an ingested event.

    These labels describe how much the pipeline can trust the
    contents of the event payload. They are set by upstream
    collectors/transforms and consumed by downstream policy and
    detection logic to decide how the payload may be used.
    """

    model_config = ConfigDict(extra="forbid")

    sanitized: bool = Field(
        default=False,
        description=(
            "True if the payload has been sanitized (e.g., stripped of "
            "executable content, control characters, etc.) prior to storage."
        ),
    )
    untrusted_content: bool = Field(
        default=True,
        description=(
            "True if the payload may contain untrusted content originating "
            "from outside the trust boundary (e.g., attacker-controlled "
            "strings). Defaults to True as a safe default."
        ),
    )
    provenance_verified: bool = Field(
        default=False,
        description=(
            "True if the source/collector identity and integrity of the "
            "event have been cryptographically or otherwise verified."
        ),
    )


class EventEnvelope(BaseModel):
    """Canonical, strictly-validated envelope for all SOC intake events.

    Every event entering the system—regardless of its original
    source—must be wrapped in this envelope. The envelope is
    intentionally strict (`extra="forbid"`, `strict=True`) to prevent
    schema drift and to ensure that unexpected or malformed fields are
    rejected at the boundary rather than silently propagated.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this envelope instance.",
    )
    source: Literal["wazuh", "eve", "unknown"] = Field(
        description="Identifier of the originating collector/source system.",
    )
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this envelope was received by the pipeline.",
    )

    schema_version: Literal["1.0"] = Field(
        default="1.0",
        description="Version of the canonical envelope schema.",
    )
    collector_version: str = Field(
        description="Version identifier of the collector that produced this event.",
    )
    transform_version: str = Field(
        description="Version identifier of the transform that normalized this event.",
    )

    original_payload_hash: str = Field(
        description="Hash of the original, unmodified payload as received from the source.",
    )
    normalized_payload_hash: str = Field(
        description="Hash of the normalized/sanitized payload stored in `payload`.",
    )

    trust_labels: TrustLabels = Field(
        default_factory=TrustLabels,
        description="Provenance and trust metadata for this event.",
    )

    # NOTE: `Dict[str, Any]` is intentional here. The payload has already
    # been sanitized/normalized upstream (see `trust_labels.sanitized` and
    # `normalized_payload_hash`); this envelope does not further constrain
    # its internal shape, since payload schemas vary by source.
    payload: Dict[str, Any] = Field(
        description="Strictly sanitized event payload. Must not contain arbitrary nested execution.",
    )
