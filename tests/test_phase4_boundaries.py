"""
Tests for Phase 4 Execution Isolation and Queue Authority.
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.strict_queue_transitions import authorize_transition, StateTransitionViolation

def test_critical_job_requires_approval_for_completion():
    """P1-4 Invariant: CRITICAL jobs cannot complete without approval."""
    job = {"priority": "CRITICAL", "approval": {"approved": False}}
    
    with pytest.raises(StateTransitionViolation, match="without explicit approval"):
        authorize_transition("processing", "completed", job)

def test_critical_job_with_approval_can_complete():
    """P1-4 Invariant: Approved CRITICAL jobs can complete."""
    job = {"priority": "CRITICAL", "approval": {"approved": True, "by": "human"}}
    assert authorize_transition("processing", "completed", job) is True

def test_normal_job_can_complete_without_approval():
    """P1-4 Invariant: Non-critical jobs are unaffected by the approval gate."""
    job = {"priority": "normal", "approval": {"approved": False}}
    assert authorize_transition("processing", "completed", job) is True

def test_illegal_state_transitions_are_blocked():
    """P1-4 Invariant: Cannot jump from pending directly to completed."""
    job = {"priority": "normal"}
    with pytest.raises(StateTransitionViolation, match="Illegal transition"):
        authorize_transition("pending", "completed", job)

def test_isolated_runner_imports_cleanly():
    """P0-3 Invariant: Ensure the isolated runner module is syntactically valid."""
    from engine.isolated_worker_runner import execute_worker_in_isolation
    assert callable(execute_worker_in_isolation)
