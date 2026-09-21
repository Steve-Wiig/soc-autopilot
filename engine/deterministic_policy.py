"""Deterministic policy engine for authorizing recommended actions.

This module implements a fail-closed authorization boundary that decides
whether a model-generated recommendation may be auto-allowed, must be sent
for human review, denied outright, or treated as a no-op. Trust in the
source of a recommendation is established independently by the runtime
(via the caller-supplied `authoritative_trusted_source` flag) and can never
be granted by the model's own output.
"""

from dataclasses import dataclass
from typing import Final, FrozenSet, Literal

DecisionOutcome = Literal["ALLOW", "REVIEW", "DENY", "NO_OP"]

# Actions that are safe enough to be auto-allowed without human review,
# subject to additional severity and trust constraints enforced below.
SAFE_AUTONOMOUS_ACTIONS: Final[FrozenSet[str]] = frozenset({
    "NO_ACTION",
    "ENRICH",
})

# Control/enforcement actions that always require human review before
# being carried out, regardless of severity or trust.
REVIEW_ACTIONS: Final[FrozenSet[str]] = frozenset({
    "ESCALATE",
    "ISOLATE",
    "BLOCK",
})

# All actions recognized by this policy. Anything outside this set is
# treated as unsupported and fails closed to DENY.
KNOWN_ACTIONS: Final[FrozenSet[str]] = SAFE_AUTONOMOUS_ACTIONS | REVIEW_ACTIONS | {"OTHER"}


@dataclass
class RecommendationEnvelope:
    """A model-generated recommendation to be evaluated by the policy engine.

    Attributes:
        recommended_action: The action the model recommends (e.g. "ENRICH",
            "BLOCK"). Compared case-insensitively against known actions.
        severity: The severity level associated with the event (e.g. "LOW",
            "MEDIUM", "HIGH", "CRITICAL"). Compared case-insensitively.
        requires_human_review: If True, the model itself is requesting human
            review. This can only add caution; it can never be used to
            suppress a review that policy would otherwise require.
        event_id: Identifier of the event this recommendation pertains to.
    """

    recommended_action: str
    severity: str
    requires_human_review: bool
    event_id: str


def evaluate_deterministic_policy(
    rec: RecommendationEnvelope,
    *,
    authoritative_trusted_source: bool = False,
) -> DecisionOutcome:
    """Evaluate a recommendation against the deterministic policy.

    Deterministic authorization boundary.

    Trust is supplied independently by the runtime EventEnvelope.
    Model output cannot grant itself trust.

    Only explicitly safe recommendation actions can produce ALLOW.
    Enforcement/control actions always require REVIEW.

    Auto-allow is further restricted to LOW severity. MEDIUM, HIGH,
    and CRITICAL always require REVIEW, even for NO_ACTION/ENRICH
    with trusted provenance. The auto-allow severity band is a policy
    decision; widening it requires an explicit contract change.

    Args:
        rec: The recommendation envelope to evaluate.
        authoritative_trusted_source: Whether the runtime has independently
            established that this recommendation's provenance is trusted.
            This flag is supplied by the caller and cannot be influenced by
            the model's own output.

    Returns:
        The resulting decision outcome: "ALLOW", "REVIEW", "DENY", or
        "NO_OP".
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
