"""
Bounded development-worker orchestration.

Pipeline:
    worker proposal
        ->
    deterministic scope validation
        ->
    deterministic safety / regression gates
        ->
    3 independent approval votes (Ed25519-signed in strict mode)
        ->
    2-of-3 quorum
        ->
    caller-owned canary / Git governance

Hard gates are NOT counted as approval votes.
Aider remains an implementation worker only.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Sequence

from engine.aider_development_worker import AiderWorkerResult
from engine.development_candidate import DevelopmentCandidate
from engine.development_worker_gate import (
    QuorumDecision,
    WorkerApprovalVote,
    evaluate_worker_quorum,
    evaluate_strict_quorum,
)
from contracts.worker_identity import WorkerVote


@dataclass(frozen=True)
class WorkerApprovalResult:
    """
    Outcome of evaluating a single development-worker proposal.

    Attributes:
        approved: True if the proposal cleared quorum with no hard vetoes.
        decision: The full quorum decision, including individual votes.
        hard_vetoes: Deterministic veto reasons (empty if none). A non-empty
            tuple always implies `approved` is False, regardless of vote
            outcome.
    """
    approved: bool
    decision: QuorumDecision
    hard_vetoes: tuple[str, ...]


def _collect_hard_veto_reasons(
    result: AiderWorkerResult,
    allowed_files: Sequence[str | Path],
    safety_ok: bool,
    regression_ok: bool,
    safety_reason: str,
    regression_reason: str,
) -> List[str]:
    """
    Run deterministic hard-veto checks shared by the legacy and strict paths.

    These checks are independent of and precede the approval-vote quorum:
    a hard veto reason always blocks approval, no matter how the votes fall.

    Args:
        result: The worker's execution result, including changed files.
        allowed_files: The set of file paths the worker was permitted to touch.
        safety_ok: Result of the deterministic safety gate.
        regression_ok: Result of the acceptance/regression test gate.
        safety_reason: Human-readable explanation when safety_ok is False.
        regression_reason: Human-readable explanation when regression_ok is False.

    Returns:
        A list of human-readable veto reasons. Empty if no hard veto applies.
    """
    allowed = {str(Path(p)) for p in allowed_files}
    changed = {str(Path(p)) for p in result.changed_files}
    hard_vetoes: List[str] = []
    if not result.success:
        hard_vetoes.append(f"Worker failed: {result.reason}")
    if not changed:
        hard_vetoes.append("Worker produced no changed files.")
    unauthorized = sorted(changed - allowed)
    if unauthorized:
        hard_vetoes.append("Unauthorized worker paths: " + ", ".join(unauthorized))
    if not safety_ok:
        hard_vetoes.append(safety_reason or "Deterministic safety gate failed.")
    if not regression_ok:
        hard_vetoes.append(regression_reason or "Acceptance/regression tests failed.")
    return hard_vetoes


def evaluate_worker_proposal(
    result: AiderWorkerResult,
    allowed_files: Sequence[str | Path],
    *,
    votes: Sequence[WorkerApprovalVote],
    safety_ok: bool,
    regression_ok: bool,
    safety_reason: str = "",
    regression_reason: str = "",
) -> WorkerApprovalResult:
    """
    Evaluate a worker proposal via the legacy (unsigned) approval path.

    Prefer `evaluate_strict_proposal` for production use, where votes are
    cryptographically verified against known worker identities.

    Args:
        result: The worker's execution result.
        allowed_files: The set of file paths the worker was permitted to touch.
        votes: Unsigned approval votes to evaluate against quorum rules.
        safety_ok: Result of the deterministic safety gate.
        regression_ok: Result of the acceptance/regression test gate.
        safety_reason: Human-readable explanation when safety_ok is False.
        regression_reason: Human-readable explanation when regression_ok is False.

    Returns:
        The combined approval result, including any hard vetoes and the
        underlying quorum decision.
    """
    hard_vetoes = _collect_hard_veto_reasons(
        result, allowed_files, safety_ok, regression_ok,
        safety_reason, regression_reason,
    )
    decision = evaluate_worker_quorum(list(votes), hard_vetoes=hard_vetoes)
    return WorkerApprovalResult(
        approved=decision.approved,
        decision=decision,
        hard_vetoes=tuple(hard_vetoes),
    )


def evaluate_strict_proposal(
    candidate: DevelopmentCandidate,
    result: AiderWorkerResult,
    allowed_files: Sequence[str | Path],
    *,
    votes: List[WorkerVote],
    safety_ok: bool,
    regression_ok: bool,
    key_registry: Any = None,
    safety_reason: str = "",
    regression_reason: str = "",
) -> WorkerApprovalResult:
    """
    Evaluate a worker proposal via the strict, Ed25519-verified approval path.

    This is the production evaluation path. It requires:
      - A `DevelopmentCandidate` with `generator_worker_id` and `diff_sha256`.
      - A list of 3 Ed25519-signed `WorkerVote` objects.
      - A `WorkerKeyRegistry` (or compatible object) for signature verification.

    Args:
        candidate: The development candidate under review, identifying the
            generating worker and the diff being voted on.
        result: The worker's execution result.
        allowed_files: The set of file paths the worker was permitted to touch.
        votes: Signed approval votes to verify and evaluate against quorum rules.
        safety_ok: Result of the deterministic safety gate.
        regression_ok: Result of the acceptance/regression test gate.
        key_registry: Registry used to verify vote signatures against known
            worker public keys.
        safety_reason: Human-readable explanation when safety_ok is False.
        regression_reason: Human-readable explanation when regression_ok is False.

    Returns:
        The combined approval result, including any hard vetoes and the
        underlying quorum decision.
    """
    hard_vetoes = _collect_hard_veto_reasons(
        result, allowed_files, safety_ok, regression_ok,
        safety_reason, regression_reason,
    )
    decision = evaluate_strict_quorum(
        candidate, votes,
        hard_vetoes=hard_vetoes,
        key_registry=key_registry,
    )
    return WorkerApprovalResult(
        approved=decision.approved,
        decision=decision,
        hard_vetoes=tuple(hard_vetoes),
    )
