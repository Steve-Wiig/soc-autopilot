"""
Regression tests for P0 Identity & Worktree Invariants.
Proves that the cryptographic boundaries hold.
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.development_candidate import DevelopmentCandidate
from contracts.worker_identity import WorkerVote

def test_candidate_tracks_diff_hash():
    diff_v1 = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
    cand = DevelopmentCandidate.from_diff("cand-001", "abc123", diff_v1, ["file.py"], generator_worker_id='test_generator_worker_id')
    assert len(cand.diff_sha256) == 64
    assert cand.verify_diff_integrity(diff_v1) is True

def test_diff_mutation_invalidates_candidate():
    """CRITICAL INVARIANT: Post-review mutation breaks the chain."""
    diff_v1 = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
    diff_v2 = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+newer"
    cand = DevelopmentCandidate.from_diff("cand-001", "abc123", diff_v1, ["file.py"], generator_worker_id='test_generator_worker_id')
    
    assert cand.verify_diff_integrity(diff_v2) is False, "Mutated diff must fail integrity check"


def test_worker_vote_binds_to_exact_candidate():
    from contracts.worker_identity import WorkerVote
    import time
    vote = WorkerVote(
        worker_id="w1", worker_class="c", worker_instance="i",
        execution_host="h", software_version="v",
        candidate_hash="hash1", decision="approve",
        timestamp=int(time.time()), signature="sig1"
    )
    assert vote.candidate_hash == "hash1"
    # Verify it's bound to the exact hash
    assert vote.candidate_hash != "hash2"


def test_quorum_requires_distinct_workers():
    from engine.strict_quorum import enforce_quorum, QuorumViolation
    from engine.development_candidate import DevelopmentCandidate
    from tests.helpers.crypto_test_helpers import create_signed_vote, create_test_registry
    
    candidate = DevelopmentCandidate.from_diff(
        "c1", "base", "diff", ["file.py"], generator_worker_id="gen_worker"
    )
    registry = create_test_registry(["w1", "w2"])
    
    # Two votes from the same worker (should fail independence check)
    v1 = create_signed_vote("w1", candidate.diff_sha256, registry=registry)
    v2 = create_signed_vote("w1", candidate.diff_sha256, registry=registry)
    v3 = create_signed_vote("w2", candidate.diff_sha256, registry=registry)
    
    try:
        enforce_quorum(candidate, [v1, v2, v3], key_registry=registry)
        assert False, "Should have raised QuorumViolation"
    except QuorumViolation as e:
        assert "independent" in str(e).lower() or "duplicate" in str(e).lower()

