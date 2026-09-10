"""
Bounded development-worker orchestration.

Pipeline:

    worker proposal
        ->
    deterministic scope validation
        ->
    deterministic safety / regression gates
        ->
    3 independent approval votes
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
from typing import Sequence

from engine.aider_development_worker import AiderWorkerResult
from engine.development_worker_gate import (
    QuorumDecision,
    WorkerVote,
    evaluate_worker_quorum,
)


@dataclass(frozen=True)
class WorkerApprovalResult:
    approved: bool
    decision: QuorumDecision
    hard_vetoes: tuple[str, ...]


def evaluate_worker_proposal(
    result: AiderWorkerResult,
    allowed_files: Sequence[str | Path],
    *,
    votes: Sequence[WorkerVote],
    safety_ok: bool,
    regression_ok: bool,
    safety_reason: str = "",
    regression_reason: str = "",
) -> WorkerApprovalResult:
    """
    Evaluate a bounded worker proposal.

    Deterministic checks are absolute vetoes:
      - worker failure
      - empty change
      - unauthorized paths
      - safety failure
      - regression/acceptance failure

    Only the supplied independent WorkerVote objects participate
    in the 2-of-3 approval quorum.
    """

    allowed = {
        str(Path(path))
        for path in allowed_files
    }

    changed = {
        str(Path(path))
        for path in result.changed_files
    }

    hard_vetoes: list[str] = []

    if not result.success:
        hard_vetoes.append(
            f"Worker failed: {result.reason}"
        )

    if not changed:
        hard_vetoes.append(
            "Worker produced no changed files."
        )

    unauthorized = sorted(changed - allowed)
    if unauthorized:
        hard_vetoes.append(
            "Unauthorized worker paths: " + ", ".join(unauthorized)
        )

    if not safety_ok:
        hard_vetoes.append(
            safety_reason or "Deterministic safety gate failed."
        )

    if not regression_ok:
        hard_vetoes.append(
            regression_reason or "Acceptance/regression tests failed."
        )

    decision = evaluate_worker_quorum(
        list(votes),
        hard_vetoes=hard_vetoes,
    )

    return WorkerApprovalResult(
        approved=decision.approved,
        decision=decision,
        hard_vetoes=tuple(hard_vetoes),
    )
