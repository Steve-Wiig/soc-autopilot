"""
soc.engine.deterministic_policy.v1
Evaluates LLM recommendations against deterministic rules.
Produces a bound PolicyDecision that cannot be reused for a different incident.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

class PolicyEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    incident_id: str
    model_recommendation: str  # NO_ACTION, ENRICH, ESCALATE, ISOLATE, BLOCK, OTHER
    model_severity: str
    model_confidence: float
    requires_human_review: bool

class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    incident_id: str
    policy_version: str = "v1.0"
    authorized_action: str  # NO_ACTION, ENRICH, ESCALATE, REVIEW_REQUIRED, DENIED
    decision_reason: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

def evaluate_deterministic_policy(envelope: PolicyEnvelope) -> PolicyDecision:
    """
    Deterministic policy evaluation.
    The model only *recommends*. The policy *decides*.
    """
    action = envelope.model_recommendation.upper()
    severity = envelope.model_severity.upper()
    
    # Rule 1: High severity or low confidence always requires human review
    if severity in ["HIGH", "CRITICAL"] or envelope.model_confidence < 0.7:
        return PolicyDecision(
            incident_id=envelope.incident_id,
            authorized_action="REVIEW_REQUIRED",
            decision_reason=f"Policy override: severity={severity} or confidence={envelope.model_confidence} < 0.7"
        )
    
    # Rule 2: High-impact actions (ISOLATE, BLOCK) are never auto-authorized in Tier-1
    if action in ["ISOLATE", "BLOCK"]:
        return PolicyDecision(
            incident_id=envelope.incident_id,
            authorized_action="REVIEW_REQUIRED",
            decision_reason=f"Policy override: action '{action}' requires human authorization"
        )
    
    # Rule 3: Model explicitly requests review
    if envelope.requires_human_review:
        return PolicyDecision(
            incident_id=envelope.incident_id,
            authorized_action="REVIEW_REQUIRED",
            decision_reason="Model requested human review"
        )
    
    # Rule 4: Allow safe, low-risk actions
    if action in ["NO_ACTION", "ENRICH", "ESCALATE"]:
        return PolicyDecision(
            incident_id=envelope.incident_id,
            authorized_action=action,
            decision_reason=f"Policy allowed: {action}"
        )
    
    # Default fail-closed
    return PolicyDecision(
        incident_id=envelope.incident_id,
        authorized_action="REVIEW_REQUIRED",
        decision_reason=f"Policy fail-closed: unrecognized recommendation '{action}'"
    )
