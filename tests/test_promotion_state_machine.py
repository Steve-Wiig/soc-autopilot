import pytest
from contracts.promotion_state import PromotionState, validate_transition, TransitionError

def test_valid_forward_transitions():
    # Happy path through the standard lifecycle
    validate_transition(PromotionState.GENERATED, PromotionState.TESTED)
    validate_transition(PromotionState.TESTED, PromotionState.CANARY_PASSED)
    validate_transition(PromotionState.CANARY_PASSED, PromotionState.PENDING_HUMAN_MERGE)
    validate_transition(PromotionState.PENDING_HUMAN_MERGE, PromotionState.MERGED)

def test_valid_rejection_transitions():
    # Can reject from almost any pre-merge state
    validate_transition(PromotionState.GENERATED, PromotionState.REJECTED)
    validate_transition(PromotionState.TESTED, PromotionState.REJECTED)
    validate_transition(PromotionState.CANARY_PASSED, PromotionState.REJECTED)
    validate_transition(PromotionState.PENDING_HUMAN_MERGE, PromotionState.REJECTED)

def test_valid_revert_transition():
    # Can only revert after merge
    validate_transition(PromotionState.MERGED, PromotionState.REVERTED)

def test_invalid_bypass_to_merged():
    # GENERATED -> MERGED is strictly forbidden
    with pytest.raises(TransitionError, match="Invalid transition: GENERATED -> MERGED"):
        validate_transition(PromotionState.GENERATED, PromotionState.MERGED)

def test_invalid_bypass_canary_to_merged():
    # CANARY_PASSED -> MERGED bypasses human merge boundary
    with pytest.raises(TransitionError, match="Invalid transition: CANARY_PASSED -> MERGED"):
        validate_transition(PromotionState.CANARY_PASSED, PromotionState.MERGED)

def test_invalid_bypass_pending_to_reverted():
    # Cannot revert before it's merged
    with pytest.raises(TransitionError):
        validate_transition(PromotionState.PENDING_HUMAN_MERGE, PromotionState.REVERTED)

def test_invalid_terminal_state_transitions():
    # Cannot move out of terminal states
    with pytest.raises(TransitionError):
        validate_transition(PromotionState.REJECTED, PromotionState.MERGED)
    with pytest.raises(TransitionError):
        validate_transition(PromotionState.REVERTED, PromotionState.MERGED)
