"""
P0 Enforcement: Strict Quorum Validation.
This module enforces the cryptographic and identity invariants defined in Phase 2.
It is the final gate before a candidate can be merged.
"""
from typing import List
from engine.development_candidate import DevelopmentCandidate
from engine.worker_vote_contract import WorkerVote

class QuorumViolation(Exception):
    pass

def enforce_quorum(candidate: DevelopmentCandidate, votes: List[WorkerVote]) -> bool:
    """
    Validates a quorum of votes against a specific candidate.
    Raises QuorumViolation if any invariant is broken.
    """
    # 1. Check Vote Count
    if len(votes) != 3:
        raise QuorumViolation(f"Expected 3 votes, got {len(votes)}")

    # 2. Check Worker Independence (Distinct IDs)
    worker_ids = [v.worker_id for v in votes]
    if len(set(worker_ids)) != 3:
        raise QuorumViolation(f"Workers not independent. IDs: {worker_ids}")

    # 3. Check Cryptographic Binding (Votes must match Candidate)
    for v in votes:
        if not v.is_valid_for_candidate(candidate.diff_sha256):
            raise QuorumViolation(
                f"Vote {v.worker_id} bound to hash {v.proposal_sha256[:8]}... "
                f"does not match candidate hash {candidate.diff_sha256[:8]}..."
            )

    # 4. Check Approval Threshold (2 of 3)
    approvals = sum(1 for v in votes if v.decision == "approve")
    if approvals < 2:
        raise QuorumViolation(f"Insufficient approvals: {approvals}/3")

    return True
