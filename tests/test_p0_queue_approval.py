"""Regression test: CRITICAL jobs cannot complete without approval."""
import pytest
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

def test_critical_job_requires_approval():
    """Verify that _enforce_approval raises on unapproved CRITICAL jobs."""
    from engine.queue_manager import TriageQueueManager
    mgr = TriageQueueManager.__new__(TriageQueueManager)
    
    critical_unapproved = {"priority": "critical", "approval": {"approved": False}}
    with pytest.raises(PermissionError, match="cannot be completed without explicit approval"):
        mgr._enforce_approval("test-job-1", critical_unapproved)

def test_critical_job_with_approval_passes():
    """Verify that approved CRITICAL jobs pass the gate."""
    from engine.queue_manager import TriageQueueManager
    mgr = TriageQueueManager.__new__(TriageQueueManager)
    
    critical_approved = {"priority": "critical", "approval": {"approved": True}}
    mgr._enforce_approval("test-job-2", critical_approved)  # Should not raise

def test_noncritical_job_passes_without_approval():
    """Verify non-critical jobs are unaffected by approval gate."""
    from engine.queue_manager import TriageQueueManager
    mgr = TriageQueueManager.__new__(TriageQueueManager)
    
    normal_unapproved = {"priority": "normal", "approval": {"approved": False}}
    mgr._enforce_approval("test-job-3", normal_unapproved)  # Should not raise
