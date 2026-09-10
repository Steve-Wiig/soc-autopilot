"""
Tests for Phase 3 Enforcement and Isolation.
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.development_candidate import DevelopmentCandidate
from engine.worker_vote_contract import WorkerVote
from engine.strict_quorum import enforce_quorum, QuorumViolation

def test_enforcer_rejects_tampered_candidate():
    """Prove the enforcer catches a candidate that changed after voting."""
    diff_v1 = "original diff"
    cand = DevelopmentCandidate.from_diff("c1", "base", diff_v1, ["f.py"])
    
    # Votes are cast for v1
    votes = [
        WorkerVote("p1", cand.diff_sha256, "w1", "c", "i", "t", "approve", "r", "e"),
        WorkerVote("p1", cand.diff_sha256, "w2", "c", "i", "t", "approve", "r", "e"),
        WorkerVote("p1", cand.diff_sha256, "w3", "c", "i", "t", "approve", "r", "e"),
    ]
    
    # Tamper with candidate (simulate post-review mutation)
    cand.diff_sha256 = "tampered_hash"
    
    with pytest.raises(QuorumViolation, match="does not match candidate hash"):
        enforce_quorum(cand, votes)

def test_enforcer_rejects_non_independent_workers():
    """Prove the enforcer catches duplicate worker IDs."""
    cand = DevelopmentCandidate.from_diff("c1", "base", "diff", ["f.py"])
    votes = [
        WorkerVote("p1", cand.diff_sha256, "worker-A", "c", "i", "t", "approve", "r", "e"),
        WorkerVote("p1", cand.diff_sha256, "worker-B", "c", "i", "t", "approve", "r", "e"),
        WorkerVote("p1", cand.diff_sha256, "worker-A", "c", "i", "t", "approve", "r", "e"), # Duplicate
    ]
    with pytest.raises(QuorumViolation, match="Workers not independent"):
        enforce_quorum(cand, votes)

def test_enforcer_accepts_valid_quorum():
    """Prove a valid quorum passes."""
    cand = DevelopmentCandidate.from_diff("c1", "base", "diff", ["f.py"])
    votes = [
        WorkerVote("p1", cand.diff_sha256, "w1", "c", "i", "t", "approve", "r", "e"),
        WorkerVote("p1", cand.diff_sha256, "w2", "c", "i", "t", "approve", "r", "e"),
        WorkerVote("p1", cand.diff_sha256, "w3", "c", "i", "t", "reject", "r", "e"), # 2/3 is enough
    ]
    assert enforce_quorum(cand, votes) is True
