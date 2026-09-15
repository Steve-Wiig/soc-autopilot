import time
"""
Tests for Phase 3 Enforcement and Isolation.
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.development_candidate import DevelopmentCandidate
from contracts.worker_identity import WorkerVote
from engine.strict_quorum import enforce_quorum, QuorumViolation


def test_enforcer_rejects_tampered_candidate():
    from engine.strict_quorum import enforce_quorum, QuorumViolation
    from engine.development_candidate import DevelopmentCandidate
    from tests.helpers.crypto_test_helpers import create_signed_vote, create_test_registry
    
    candidate = DevelopmentCandidate.from_diff(
        "c1", "base", "diff", ["file.py"], generator_worker_id="gen_worker"
    )
    registry = create_test_registry(["w1", "w2", "w3"])
    
    # Votes for a DIFFERENT hash (should fail candidate binding)
    v1 = create_signed_vote("w1", "tampered_hash", registry=registry)
    v2 = create_signed_vote("w2", "tampered_hash", registry=registry)
    v3 = create_signed_vote("w3", "tampered_hash", registry=registry)
    
    try:
        enforce_quorum(candidate, [v1, v2, v3], key_registry=registry)
        assert False, "Should have raised QuorumViolation"
    except QuorumViolation as e:
        assert "hash" in str(e).lower()


def test_enforcer_rejects_non_independent_workers():
    from engine.strict_quorum import enforce_quorum, QuorumViolation
    from engine.development_candidate import DevelopmentCandidate
    from tests.helpers.crypto_test_helpers import create_signed_vote, create_test_registry
    
    # Generator is w1 (should fail self-voting check)
    candidate = DevelopmentCandidate.from_diff(
        "c1", "base", "diff", ["file.py"], generator_worker_id="w1"
    )
    registry = create_test_registry(["w1", "w2", "w3"])
    
    v1 = create_signed_vote("w1", candidate.diff_sha256, registry=registry)
    v2 = create_signed_vote("w2", candidate.diff_sha256, registry=registry)
    v3 = create_signed_vote("w3", candidate.diff_sha256, registry=registry)
    
    try:
        enforce_quorum(candidate, [v1, v2, v3], key_registry=registry)
        assert False, "Should have raised QuorumViolation"
    except QuorumViolation as e:
        assert "self-approval" in str(e).lower() or "generator" in str(e).lower()


def test_enforcer_accepts_valid_quorum():
    from engine.strict_quorum import enforce_quorum
    from engine.development_candidate import DevelopmentCandidate
    from tests.helpers.crypto_test_helpers import create_signed_vote, create_test_registry
    
    candidate = DevelopmentCandidate.from_diff(
        "c1", "base", "diff", ["file.py"], generator_worker_id="gen_worker"
    )
    registry = create_test_registry(["w1", "w2", "w3"])
    
    # 2 approvals, 1 rejection (should pass)
    v1 = create_signed_vote("w1", candidate.diff_sha256, decision="approve", registry=registry)
    v2 = create_signed_vote("w2", candidate.diff_sha256, decision="approve", registry=registry)
    v3 = create_signed_vote("w3", candidate.diff_sha256, decision="reject", registry=registry)
    
    assert enforce_quorum(candidate, [v1, v2, v3], key_registry=registry) is True

