from dataclasses import dataclass
from typing import Literal

DecisionOutcome = Literal["ALLOW", "REVIEW", "DENY", "NO_OP"]

SAFE_AUTONOMOUS_ACTIONS = {
    "NO_ACTION",
    "ENRICH",
}

REVIEW_ACTIONS = {
    "ESCALATE",
    "ISOLATE",
    "BLOCK",
}

KNOWN_ACTIONS = SAFE_AUTONOMOUS_ACTIONS | REVIEW_ACTIONS | {"OTHER"}


@dataclass
class RecommendationEnvelope:
    recommended_action: str
    severity: str
    requires_human_review: bool
    event_id: str


def evaluate_deterministic_policy(
    rec: RecommendationEnvelope,
    *,
    authoritative_trusted_source: bool = False,
) -> DecisionOutcome:
    """
    Deterministic authorization boundary.

    Trust is supplied independently by the runtime EventEnvelope.
    Model output cannot grant itself trust.

    Only explicitly safe recommendation actions can produce ALLOW.
    Enforcement/control actions always require REVIEW.

    Auto-allow is further restricted to LOW severity. MEDIUM, HIGH,
    and CRITICAL always require REVIEW, even for NO_ACTION/ENRICH
    with trusted provenance. The auto-allow severity band is a policy
    decision; widening it requires an explicit contract change.
    """

    action = str(rec.recommended_action).upper()
    severity = str(rec.severity).upper()

    # Unknown or explicitly unsupported actions fail closed.
    if action not in KNOWN_ACTIONS:
        return "DENY"

    # The model may request human review, but cannot suppress it.
    if rec.requires_human_review:
        return "REVIEW"

    # Control/enforcement actions are never autonomous ALLOW.
    if action in REVIEW_ACTIONS:
        return "REVIEW"

    # OTHER is intentionally non-authorizing.
    if action == "OTHER":
        return "REVIEW"

    # Safe actions may only be auto-allowed when BOTH:
    #   1. severity is LOW, and
    #   2. the runtime independently established trusted provenance.
    #
    # MEDIUM, HIGH, and CRITICAL always require REVIEW even for safe
    # actions, because severity is itself a signal that a human should
    # see the event before any autonomous action occurs. Changing this
    # band is a policy decision, not a refactor.
    if (
        action in SAFE_AUTONOMOUS_ACTIONS
        and severity == "LOW"
        and authoritative_trusted_source
    ):
        return "ALLOW"

    # Fail closed for every remaining combination.
    return "REVIEW"
