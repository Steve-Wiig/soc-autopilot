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
from typing import Iterable, List, Optional, Sequence

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
    """Outcome of a worker approval quorum evaluation."""
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
    """Evaluate a legacy 2-of-3 worker approval quorum.

    Args:
        votes: Sequence of legacy approval votes to evaluate. Exactly
            REQUIRED_VOTES distinct, well-formed votes are required.
        hard_vetoes: Iterable of veto identifiers. Any non-empty entry
            blocks approval regardless of vote outcome.

    Returns:
        A QuorumDecision describing whether quorum was reached and why.

    Note:
        Use evaluate_strict_quorum for production Ed25519-verified voting.
    """
    vetoes = tuple(str(veto).strip() for veto in hard_vetoes if str(veto).strip())
    vote_list: List = list(votes)
    judges: List[str] = [
        vote.judge.strip() for vote in vote_list if isinstance(vote, WorkerApprovalVote)
    ]
    malformed_votes: List = [
        vote for vote in vote_list if not isinstance(vote, WorkerApprovalVote)
    ]

    if len(vote_list) != REQUIRED_VOTES:
        return QuorumDecision(
            approved=False,
            approval_count=sum(
                1 for vote in vote_list
                if isinstance(vote, WorkerApprovalVote) and vote.approve is True
            ),
            vote_count=len(vote_list),
            required_approvals=REQUIRED_APPROVALS,
            required_votes=REQUIRED_VOTES,
            hard_vetoes=vetoes,
            reason=f"Expected exactly {REQUIRED_VOTES} votes; received {len(vote_list)}.",
        )

    if malformed_votes:
        return QuorumDecision(
            approved=False,
            approval_count=0,
            vote_count=len(vote_list),
            required_approvals=REQUIRED_APPROVALS,
            required_votes=REQUIRED_VOTES,
            hard_vetoes=vetoes,
            reason="Malformed worker vote detected.",
        )

    if len(set(judges)) != REQUIRED_VOTES or any(not judge for judge in judges):
        return QuorumDecision(
            approved=False,
            approval_count=sum(1 for vote in vote_list if vote.approve is True),
            vote_count=len(vote_list),
            required_approvals=REQUIRED_APPROVALS,
            required_votes=REQUIRED_VOTES,
            hard_vetoes=vetoes,
            reason="Worker judges must be three distinct non-empty identities.",
        )

    approval_count = sum(1 for vote in vote_list if vote.approve is True)

    if vetoes:
        return QuorumDecision(
            approved=False,
            approval_count=approval_count,
            vote_count=len(vote_list),
            required_approvals=REQUIRED_APPROVALS,
            required_votes=REQUIRED_VOTES,
            hard_vetoes=vetoes,
            reason="Hard safety veto prevents quorum approval.",
        )

    approved = approval_count >= REQUIRED_APPROVALS
    return QuorumDecision(
        approved=approved,
        approval_count=approval_count,
        vote_count=len(vote_list),
        required_approvals=REQUIRED_APPROVALS,
        required_votes=REQUIRED_VOTES,
        hard_vetoes=(),
        reason=(
            f"{approval_count}/{REQUIRED_VOTES} worker approvals; "
            f"{REQUIRED_APPROVALS}/{REQUIRED_VOTES} required."
        ),
    )


def evaluate_strict_quorum(
    candidate: DevelopmentCandidate,
    votes: List[WorkerVote],
    hard_vetoes: Iterable[str] = (),
    key_registry: Optional[object] = None,
) -> QuorumDecision:
    """Evaluate a strict, Ed25519-verified 2-of-3 worker approval quorum.

    Args:
        candidate: The development candidate under evaluation.
        votes: List of cryptographically signed worker votes.
        hard_vetoes: Iterable of veto identifiers. Any non-empty entry
            blocks approval regardless of vote outcome.
        key_registry: Optional registry used to resolve and verify
            worker signing keys.

    Returns:
        A QuorumDecision describing whether quorum was reached and why.
    """
    vetoes = tuple(str(veto).strip() for veto in hard_vetoes if str(veto).strip())

    if vetoes:
        return QuorumDecision(
            approved=False,
            approval_count=0,
            vote_count=len(votes),
            required_approvals=REQUIRED_APPROVALS,
            required_votes=REQUIRED_VOTES,
            hard_vetoes=vetoes,
            reason="Hard safety veto prevents quorum approval.",
        )

    try:
        enforce_quorum(candidate, votes, key_registry=key_registry)
        approvals = sum(1 for vote in votes if str(vote.decision).lower() == "approve")
        return QuorumDecision(
            approved=True,
            approval_count=approvals,
            vote_count=len(votes),
            required_approvals=REQUIRED_APPROVALS,
            required_votes=REQUIRED_VOTES,
            hard_vetoes=(),
            reason="Strict quorum validated with Ed25519 identity verification.",
        )
    except QuorumViolation as error:
        return QuorumDecision(
            approved=False,
            approval_count=0,
            vote_count=len(votes),
            required_approvals=REQUIRED_APPROVALS,
            required_votes=REQUIRED_VOTES,
            hard_vetoes=vetoes,
            reason=str(error),
        )
