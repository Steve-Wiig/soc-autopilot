"""
P0 Enforcement: Strict Quorum Validation.
This module enforces the cryptographic and identity invariants defined in Phase 2.
It is the final gate before a candidate can be merged.
"""
from typing import List
from engine.development_candidate import DevelopmentCandidate
from engine.worker_vote_contract import WorkerVote
from contracts.worker_vote_adapter import normalize_worker_vote
from contracts.worker_identity import VoteValidator

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

    # 3. Normalize and apply hardened identity validation
    validator = VoteValidator()

    for v in votes:
        try:
            normalized = normalize_worker_vote(v)
            validator.validate(
                normalized,
                candidate.diff_sha256
            )
        except Exception as exc:
            message = str(exc)

            if "Wrong candidate hash" in message:
                raise QuorumViolation(
                    f"Vote {v.worker_id} does not match candidate hash"
                )

            raise QuorumViolation(
                f"Worker vote identity validation failed: {exc}"
            )

    # 4. Check Approval Threshold (2 of 3)
    approvals = sum(1 for v in votes if v.decision == "approve")
    if approvals < 2:
        raise QuorumViolation(f"Insufficient approvals: {approvals}/3")

    return True
