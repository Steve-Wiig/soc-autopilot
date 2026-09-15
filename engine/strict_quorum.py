"""
P0 Enforcement: Strict Quorum with Ed25519 identity verification.
This module enforces the cryptographic and identity invariants.
It is the final gate before a candidate can be merged.
"""
from typing import List, Optional
from engine.development_candidate import DevelopmentCandidate
from contracts.worker_identity import WorkerVote, VoteValidator


class QuorumViolation(Exception):
    pass


def enforce_quorum(
    candidate: DevelopmentCandidate,
    votes: List[WorkerVote],
    key_registry=None,
) -> bool:
    """
    Validates a quorum of Ed25519-signed votes against a candidate.
    Raises QuorumViolation if any invariant is broken.
    """
    # 1. Check Vote Count
    if len(votes) != 3:
        raise QuorumViolation(f"Expected 3 votes, got {len(votes)}")

    # 2. Check Worker Independence (Distinct IDs)
    worker_ids = [v.worker_id for v in votes]
    if len(set(worker_ids)) != 3:
        raise QuorumViolation(f"Workers not independent. IDs: {worker_ids}")

    # 2.5. Check Generator Independence (No Self-Voting)
    if candidate.generator_worker_id in worker_ids:
        raise QuorumViolation(
            f"Quorum violation: Candidate generator '{candidate.generator_worker_id}' "
            "is present in the voting quorum. Self-approval is forbidden."
        )

    # 3. Validate each vote (candidate hash + Ed25519 signature)
    validator = VoteValidator(key_registry=key_registry)

    for v in votes:
        if v.candidate_hash != candidate.diff_sha256:
            raise QuorumViolation(
                f"Vote {v.worker_id} does not match candidate hash"
            )
        try:
            validator.validate(v, candidate.diff_sha256)
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
    approvals = sum(
        1 for v in votes if str(v.decision).lower() == "approve"
    )
    if approvals < 2:
        raise QuorumViolation(f"Insufficient approvals: {approvals}/3")

    return True
