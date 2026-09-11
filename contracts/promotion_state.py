from enum import Enum

class PromotionState(Enum):
    """Explicit states for the candidate promotion lifecycle."""
    GENERATED = "GENERATED"
    TESTED = "TESTED"
    CANARY_PASSED = "CANARY_PASSED"
    PENDING_HUMAN_MERGE = "PENDING_HUMAN_MERGE"
    MERGED = "MERGED"
    REJECTED = "REJECTED"
    REVERTED = "REVERTED"

class TransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass

# Explicit map of allowed transitions.
# Any transition not listed here is strictly forbidden.
TRANSITIONS = {
    PromotionState.GENERATED: {PromotionState.TESTED, PromotionState.REJECTED},
    PromotionState.TESTED: {PromotionState.CANARY_PASSED, PromotionState.REJECTED},
    PromotionState.CANARY_PASSED: {PromotionState.PENDING_HUMAN_MERGE, PromotionState.REJECTED},
    PromotionState.PENDING_HUMAN_MERGE: {PromotionState.MERGED, PromotionState.REJECTED},
    PromotionState.MERGED: {PromotionState.REVERTED},
    PromotionState.REJECTED: set(),
    PromotionState.REVERTED: set(),
}

def validate_transition(current: PromotionState, proposed: PromotionState) -> None:
    """
    Validates a state transition.
    Raises TransitionError if the proposed state violates the state machine rules.
    """
    if not isinstance(current, PromotionState) or not isinstance(proposed, PromotionState):
        raise TransitionError("Both states must be valid PromotionState enums.")

    allowed_next_states = TRANSITIONS.get(current, set())

    if proposed not in allowed_next_states:
        raise TransitionError(
            f"Invalid transition: {current.value} -> {proposed.value}. "
            f"Allowed transitions: {[s.value for s in allowed_next_states]}"
        )
