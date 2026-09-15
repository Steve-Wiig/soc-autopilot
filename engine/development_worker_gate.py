"""
Development-worker approval quorum.
Supports both legacy (string-based) and strict (Ed25519) evaluation.

Rules:
- Exactly three distinct worker approval votes are required.
- At least 2 of 3 approvals are required.
- Any hard safety veto rejects the proposal regardless of quorum.
- Missing, duplicate, or malformed votes cannot accidentally approve.
- Strict path enforces Ed25519 identity verification.
"""
from dataclasses import dataclass
from typing import Iterable, Sequence, List, Optional

from contracts.worker_identity import WorkerVote
from engine.strict_quorum import enforce_quorum, QuorumViolation
from engine.development_candidate import DevelopmentCandidate

REQUIRED_VOTES = 3
REQUIRED_APPROVALS = 2


@dataclass(frozen=True)
class WorkerApprovalVote:
    """Legacy vote type. Use contracts.worker_identity.WorkerVote for production."""
    judge: str
    approve: bool
    reason: str = ""


@dataclass(frozen=True)
class QuorumDecision:
    approved: bool
    approval_count: int
    vote_count: int
    required_approvals: int
    required_votes: int
    hard_vetoes: tuple
    reason: str


def evaluate_worker_quorum(
    votes: Sequence[WorkerApprovalVote],
    hard_vetoes: Iterable[str] = (),
) -> QuorumDecision:
    """Legacy 2-of-3 evaluation. Use evaluate_strict_quorum for production."""
    vetoes = tuple(str(v).strip() for v in hard_vetoes if str(v).strip())
    vote_list = list(votes)
    judges = [v.judge.strip() for v in vote_list if isinstance(v, WorkerApprovalVote)]
    malformed = [v for v in vote_list if not isinstance(v, WorkerApprovalVote)]

    if len(vote_list) != REQUIRED_VOTES:
        return QuorumDecision(
            approved=False,
            approval_count=sum(1 for v in vote_list if isinstance(v, WorkerApprovalVote) and v.approve is True),
            vote_count=len(vote_list),
            required_approvals=REQUIRED_APPROVALS,
            required_votes=REQUIRED_VOTES,
            hard_vetoes=vetoes,
            reason=f"Expected exactly {REQUIRED_VOTES} votes; received {len(vote_list)}.",
        )

    if malformed:
        return QuorumDecision(False, 0, len(vote_list), REQUIRED_APPROVALS, REQUIRED_VOTES, vetoes, "Malformed worker vote detected.")

    if len(set(judges)) != REQUIRED_VOTES or any(not j for j in judges):
        return QuorumDecision(
            False,
            sum(1 for v in vote_list if v.approve is True),
            len(vote_list), REQUIRED_APPROVALS, REQUIRED_VOTES, vetoes,
            "Worker judges must be three distinct non-empty identities.",
        )

    approval_count = sum(1 for v in vote_list if v.approve is True)

    if vetoes:
        return QuorumDecision(False, approval_count, len(vote_list), REQUIRED_APPROVALS, REQUIRED_VOTES, vetoes, "Hard safety veto prevents quorum approval.")

    approved = approval_count >= REQUIRED_APPROVALS
    return QuorumDecision(
        approved, approval_count, len(vote_list),
        REQUIRED_APPROVALS, REQUIRED_VOTES, (),
        f"{approval_count}/{REQUIRED_VOTES} worker approvals; {REQUIRED_APPROVALS}/{REQUIRED_VOTES} required.",
    )


def evaluate_strict_quorum(
    candidate: DevelopmentCandidate,
    votes: List[WorkerVote],
    hard_vetoes: Iterable[str] = (),
    key_registry=None,
) -> QuorumDecision:
    """Strict Ed25519-verified 2-of-3 quorum evaluation."""
    vetoes = tuple(str(v).strip() for v in hard_vetoes if str(v).strip())

    if vetoes:
        return QuorumDecision(
            False, 0, len(votes), REQUIRED_APPROVALS, REQUIRED_VOTES,
            vetoes, "Hard safety veto prevents quorum approval.",
        )

    try:
        enforce_quorum(candidate, votes, key_registry=key_registry)
        approvals = sum(1 for v in votes if str(v.decision).lower() == "approve")
        return QuorumDecision(
            True, approvals, len(votes), REQUIRED_APPROVALS, REQUIRED_VOTES,
            (), "Strict quorum validated with Ed25519 identity verification.",
        )
    except QuorumViolation as e:
        return QuorumDecision(
            False, 0, len(votes), REQUIRED_APPROVALS, REQUIRED_VOTES,
            vetoes, str(e),
        )
