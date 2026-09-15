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
from typing import Sequence, List, Optional

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
    approved: bool
    decision: QuorumDecision
    hard_vetoes: tuple


def _check_hard_vetoes(
    result: AiderWorkerResult,
    allowed_files: Sequence[str | Path],
    safety_ok: bool,
    regression_ok: bool,
    safety_reason: str,
    regression_reason: str,
) -> list[str]:
    """Deterministic hard veto checks. Shared by legacy and strict paths."""
    allowed = {str(Path(p)) for p in allowed_files}
    changed = {str(Path(p)) for p in result.changed_files}
    hard_vetoes: list[str] = []
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
    """Legacy evaluation path. Use evaluate_strict_proposal for production."""
    hard_vetoes = _check_hard_vetoes(
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
    key_registry=None,
    safety_reason: str = "",
    regression_reason: str = "",
) -> WorkerApprovalResult:
    """
    Strict Ed25519-verified evaluation path.

    Requires:
      - A DevelopmentCandidate with generator_worker_id and diff_sha256.
      - A list of 3 Ed25519-signed WorkerVote objects.
      - A WorkerKeyRegistry for signature verification.
    """
    hard_vetoes = _check_hard_vetoes(
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
