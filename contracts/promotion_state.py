"""State machine contract for the candidate promotion lifecycle.

This module defines the valid states a promotion candidate can be in,
along with the explicit set of allowed transitions between those states.
Any transition not explicitly listed in ``TRANSITIONS`` is forbidden and
will raise a :class:`TransitionError` when attempted.
"""

from enum import Enum
from typing import Dict, FrozenSet

__all__ = ["PromotionState", "TransitionError", "TRANSITIONS", "validate_transition"]


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


# Explicit, immutable map of allowed transitions.
# Any transition not listed here is strictly forbidden.
TRANSITIONS: Dict[PromotionState, FrozenSet[PromotionState]] = {
    PromotionState.GENERATED: frozenset({PromotionState.TESTED, PromotionState.REJECTED}),
    PromotionState.TESTED: frozenset({PromotionState.CANARY_PASSED, PromotionState.REJECTED}),
    PromotionState.CANARY_PASSED: frozenset({PromotionState.PENDING_HUMAN_MERGE, PromotionState.REJECTED}),
    PromotionState.PENDING_HUMAN_MERGE: frozenset({PromotionState.MERGED, PromotionState.REJECTED}),
    PromotionState.MERGED: frozenset({PromotionState.REVERTED}),
    PromotionState.REJECTED: frozenset(),
    PromotionState.REVERTED: frozenset(),
}


def validate_transition(current: PromotionState, proposed: PromotionState) -> None:
    """Validate a proposed state transition.

    Args:
        current: The promotion candidate's current state.
        proposed: The state the candidate is attempting to transition to.

    Raises:
        TransitionError: If either argument is not a valid ``PromotionState``,
            or if the proposed transition is not allowed from the current state.
    """
    if not isinstance(current, PromotionState) or not isinstance(proposed, PromotionState):
        raise TransitionError("Both states must be valid PromotionState enums.")

    allowed_target_states = TRANSITIONS.get(current, frozenset())

    if proposed not in allowed_target_states:
        raise TransitionError(
            f"Invalid transition: {current.value} -> {proposed.value}. "
            f"Allowed transitions: {[state.value for state in allowed_target_states]}"
        )
