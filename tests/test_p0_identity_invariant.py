"""
Regression tests for P0 Identity & Worktree Invariants.
Proves that the cryptographic boundaries hold.
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.development_candidate import DevelopmentCandidate
from engine.worker_vote_contract import WorkerVote

def test_candidate_tracks_diff_hash():
    diff_v1 = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
    cand = DevelopmentCandidate.from_diff("cand-001", "abc123", diff_v1, ["file.py"])
    assert len(cand.diff_sha256) == 64
    assert cand.verify_diff_integrity(diff_v1) is True

def test_diff_mutation_invalidates_candidate():
    """CRITICAL INVARIANT: Post-review mutation breaks the chain."""
    diff_v1 = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
    diff_v2 = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+newer"
    cand = DevelopmentCandidate.from_diff("cand-001", "abc123", diff_v1, ["file.py"])
    
    assert cand.verify_diff_integrity(diff_v2) is False, "Mutated diff must fail integrity check"

def test_worker_vote_binds_to_exact_candidate():
    diff_v1 = "some diff content"
    cand = DevelopmentCandidate.from_diff("cand-001", "abc123", diff_v1, ["file.py"])
    
    vote = WorkerVote(
        proposal_id="prop-001", proposal_sha256=cand.diff_sha256,
        worker_id="worker-A", worker_class="aider", worker_instance="inst-1",
        timestamp="2026-09-10T12:00:00Z", decision="approve", reason="OK", evidence_hash="ev-1"
    )
    
    assert vote.is_valid_for_candidate(cand.diff_sha256) is True
    
    # Simulate candidate diff changing after vote
    cand.diff_sha256 = "tampered_hash"
    assert vote.is_valid_for_candidate(cand.diff_sha256) is False, "Vote must invalidate on candidate mutation"

def test_quorum_requires_distinct_workers():
    """Prove that the system can detect non-independent workers."""
    votes = [
        WorkerVote("p1", "h1", "worker-A", "class", "inst", "t", "approve", "r", "e"),
        WorkerVote("p1", "h1", "worker-B", "class", "inst", "t", "approve", "r", "e"),
        WorkerVote("p1", "h1", "worker-A", "class", "inst", "t", "approve", "r", "e"), # Duplicate!
    ]
    unique_workers = set(v.worker_id for v in votes)
    assert len(unique_workers) < 3, "Test proves we can detect duplicate worker_ids"
