"""
Development-worker approval quorum.

This module is intentionally independent from engine.consensus_gate.py.

Rules:
- Exactly three distinct worker approval votes are required.
- At least 2 of 3 approvals are required.
- Any hard safety veto rejects the proposal regardless of quorum.
- Missing, duplicate, or malformed votes cannot accidentally approve.
"""

from dataclasses import dataclass
from typing import Iterable, Sequence


REQUIRED_VOTES = 3
REQUIRED_APPROVALS = 2


@dataclass(frozen=True)
class WorkerApprovalVote:
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
    hard_vetoes: tuple[str, ...]
    reason: str


def evaluate_worker_quorum(
    votes: Sequence[WorkerApprovalVote],
    hard_vetoes: Iterable[str] = (),
) -> QuorumDecision:
    """Evaluate the 2-of-3 development-worker approval rule."""

    vetoes = tuple(str(v).strip() for v in hard_vetoes if str(v).strip())
    vote_list = list(votes)

    judges = [vote.judge.strip() for vote in vote_list if isinstance(vote, WorkerApprovalVote)]
    malformed = [vote for vote in vote_list if not isinstance(vote, WorkerApprovalVote)]

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
            reason=(
                f"Expected exactly {REQUIRED_VOTES} votes; "
                f"received {len(vote_list)}."
            ),
        )

    if malformed:
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
