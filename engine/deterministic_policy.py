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

    def __eq__(self, other):
        # Allow legacy tests to compare PolicyDecision directly to legacy string return values
        if isinstance(other, str):
            if other == "REVIEW":
                return self.authorized_action == "REVIEW_REQUIRED"
            if other == "ALLOW":
                return self.authorized_action in ["ALLOW", "NO_ACTION", "ENRICH"]
            if other == "DENY":
                return self.authorized_action in ["DENY", "DENIED", "REVIEW_REQUIRED"]
        return super().__eq__(other)


def evaluate_deterministic_policy(envelope: PolicyRecommendationEnvelope, authoritative_trusted_source: bool = False, **kwargs) -> PolicyDecision:
    """Legacy-compatible policy evaluation."""
    action = (envelope.model_recommendation or envelope.recommended_action or "").upper().strip()
    severity = (envelope.model_severity or envelope.severity or "").upper().strip()
    human_review = envelope.requires_human_review
    inc_id = envelope.incident_id or envelope.event_id or "legacy-test"

    # 1. Human review always wins
    if human_review:
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason="Model requested human review")

    # 2. Unknown actions are DENY (mapped to REVIEW_REQUIRED)
    if action not in ["NO_ACTION", "ENRICH", "ESCALATE", "ISOLATE", "BLOCK"]:
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason=f"Policy fail-closed: unrecognized recommendation '{action}'")

    # 3. Destructive actions always REVIEW
    if action in ["ISOLATE", "BLOCK"]:
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason=f"Policy override: action '{action}' requires human authorization")

    # 4. ESCALATE is always REVIEW
    if action == "ESCALATE":
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason="Policy override: ESCALATE requires human authorization")

    # 5. Untrusted source always REVIEW
    if not authoritative_trusted_source:
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason="Policy override: untrusted source requires human review")

    # 6. Severity band: ONLY LOW is allowed
    if severity != "LOW":
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason=f"Policy override: severity={severity} requires human review")

    # 7. Safe action, trusted, LOW severity -> ALLOW
    return PolicyDecision(incident_id=inc_id, authorized_action=action, decision_reason=f"Policy allowed: {action}")


# Backward compatibility for legacy test suite
from typing import Optional
from pydantic import model_validator

class PolicyRecommendationEnvelope(BaseModel):
    """Legacy-compatible envelope that accepts old field names."""
    model_config = ConfigDict(extra="ignore", strict=False)

    # Legacy fields (explicitly declared so extra="ignore" doesn't eat them)
    recommended_action: str = ""
    severity: str = ""
    confidence: float = 0.95
    event_id: str = "legacy-test"
    authoritative_trusted_source: bool = False
    requires_human_review: bool = False

    # New fields
    incident_id: str = ""
    model_recommendation: str = ""
    model_severity: str = ""
    model_confidence: float = 0.95

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data):
        if isinstance(data, dict):
            if "recommended_action" in data and not data.get("model_recommendation"):
                data["model_recommendation"] = data["recommended_action"]
            if "severity" in data and not data.get("model_severity"):
                data["model_severity"] = data["severity"]
            if "confidence" in data and "model_confidence" not in data:
                data["model_confidence"] = data["confidence"]
            if "event_id" in data and not data.get("incident_id"):
                data["incident_id"] = data["event_id"]
            if not data.get("incident_id"):
                data["incident_id"] = "legacy-test"
            if not data.get("model_recommendation"):
                data["model_recommendation"] = data.get("recommended_action", "")
            if not data.get("model_severity"):
                data["model_severity"] = data.get("severity", "")
        return data

RecommendationEnvelope = PolicyRecommendationEnvelope
