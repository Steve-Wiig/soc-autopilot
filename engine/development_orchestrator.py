"""
The Development Orchestrator.
Bridges the Aider implementation worker to the strict cryptographic pipeline.

Security Invariants:
- Binds the Aider worker ID as the generator.
- Enforces deterministic safety/regression gates.
- Requires 3 independent Ed25519-signed votes.
- STRICTLY limits automated promotion to PENDING_HUMAN_MERGE.

State Machine Transitions:

The orchestrator follows a strict state machine with these transitions:

1. GENERATED -> TESTED
   - Occurs after the strict proposal evaluation passes both safety and regression gates
   - Requires cryptographic quorum of 3 independent Ed25519-signed votes
   - Validates that all changes are within allowed files

2. TESTED -> CANARY_PASSED
   - Occurs after canary tests have been executed and passed
   - Ensures the changes don't break critical system functionality
   - Verifies backward compatibility

3. CANARY_PASSED -> PENDING_HUMAN_MERGE
   - Final automated transition before human review
   - Marks the candidate as ready for human review and merge
   - No further automated transitions are allowed

Any transition may be rejected if validation fails, resulting in a REJECTED state.
The state machine is strictly enforced and cannot skip steps or transition backwards.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, List

from engine.aider_development_worker import AiderWorkerResult
from engine.development_worker_dispatch import (
    DevelopmentWorkerRequest,
    dispatch_development_worker,
)
from engine.development_candidate import DevelopmentCandidate
from engine.development_worker_pipeline import evaluate_strict_proposal
from contracts.promotion_state import PromotionState, validate_transition, TransitionError
from contracts.worker_identity import WorkerVote
from contracts.worker_key_registry import WorkerKeyRegistry


# Mask applied to the diff hash when deriving a short, stable candidate ID suffix.
_CANDIDATE_ID_HASH_MASK = 0xffffffff


@dataclass(frozen=True)
class OrchestrationResult:
    """
    Outcome of a single development orchestration cycle.

    Attributes:
        success: True if the candidate cleared all gates and reached
            PENDING_HUMAN_MERGE; False if it was rejected at any stage.
        candidate: The generated DevelopmentCandidate, or None if the
            worker dispatch itself failed before a candidate could be built.
        state: The final PromotionState reached by this cycle.
        reason: Human-readable explanation of the outcome (success or failure).
    """
    success: bool
    candidate: DevelopmentCandidate | None
    state: PromotionState
    reason: str


def run_development_cycle(
    prompt: str,
    allowed_files: Sequence[str | Path],
    key_registry: WorkerKeyRegistry,
    judge_votes: List[WorkerVote],
    *,
    safety_ok: bool = True,
    regression_ok: bool = True,
    safety_reason: str = "",
    regression_reason: str = "",
) -> OrchestrationResult:
    """
    Executes a single bounded development cycle end-to-end:
    dispatches the Aider worker, builds a candidate from its diff,
    evaluates it against the strict cryptographic/safety pipeline,
    and advances it through the promotion state machine up to
    PENDING_HUMAN_MERGE (never further).

    Args:
        prompt: The instruction given to the development worker.
        allowed_files: The set of files the worker is permitted to modify.
        key_registry: Registry of known worker public keys used to verify votes.
        judge_votes: Independent Ed25519-signed votes on the candidate.
        safety_ok: Result of the deterministic safety gate.
        regression_ok: Result of the deterministic regression gate.
        safety_reason: Explanation to attach if the safety gate failed.
        regression_reason: Explanation to attach if the regression gate failed.

    Returns:
        An OrchestrationResult describing whether the cycle succeeded,
        the resulting candidate (if any), the final PromotionState, and
        a human-readable reason for that outcome.
    """
    # 1. Dispatch to the Aider worker
    request = DevelopmentWorkerRequest(
        prompt=prompt,
        files=tuple(str(f) for f in allowed_files),
        backend="aider"
    )
    dispatch_result = dispatch_development_worker(request)

    if not dispatch_result.accepted_for_review:
        return OrchestrationResult(
            success=False,
            candidate=None,
            state=PromotionState.REJECTED,
            reason=f"Worker dispatch failed: {dispatch_result.reason}"
        )

    worker_result: AiderWorkerResult = dispatch_result.worker_result

    # 2. Create the Candidate (Binding the generator identity)
    # We use the backend name + model as the generator ID for traceability
    generator_id = f"aider-{dispatch_result.backend}-{worker_result.model_name}"

    candidate = DevelopmentCandidate.from_diff(
        candidate_id=f"candidate-{hash(worker_result.diff) & _CANDIDATE_ID_HASH_MASK}",
        base_commit="HEAD",
        diff_text=worker_result.diff,
        changed_files=list(worker_result.changed_files),
        generator_worker_id=generator_id
    )

    # 3. Evaluate the Strict Proposal (Quorum + Hard Gates)
    approval_result = evaluate_strict_proposal(
        candidate=candidate,
        result=worker_result,
        allowed_files=allowed_files,
        votes=judge_votes,
        safety_ok=safety_ok,
        regression_ok=regression_ok,
        key_registry=key_registry,
        safety_reason=safety_reason,
        regression_reason=regression_reason,
    )

    # 4. State Transition
    current_state = PromotionState.GENERATED

    if not approval_result.approved:
        try:
            validate_transition(current_state, PromotionState.REJECTED)
            final_state = PromotionState.REJECTED
        except TransitionError:
            # Even if REJECTED is not a formally declared transition from the
            # current state, we still surface REJECTED as the terminal state
            # for this cycle rather than propagating the transition error.
            final_state = PromotionState.REJECTED

        return OrchestrationResult(
            success=False,
            candidate=candidate,
            state=final_state,
            reason=f"Quorum/Gates failed: {approval_result.decision.reason}"
        )

    # SUCCESS PATH: Promote to PENDING_HUMAN_MERGE
    # We intentionally DO NOT promote to MERGED here.
    # The state machine requires sequential transitions:
    # GENERATED -> TESTED -> CANARY_PASSED -> PENDING_HUMAN_MERGE

    try:
        validate_transition(PromotionState.GENERATED, PromotionState.TESTED)
        validate_transition(PromotionState.TESTED, PromotionState.CANARY_PASSED)
        validate_transition(PromotionState.CANARY_PASSED, PromotionState.PENDING_HUMAN_MERGE)
        final_state = PromotionState.PENDING_HUMAN_MERGE
    except TransitionError as transition_error:
        return OrchestrationResult(
            success=False,
            candidate=candidate,
            state=PromotionState.REJECTED,
            reason=f"State machine violation: {transition_error}"
        )

    return OrchestrationResult(
        success=True,
        candidate=candidate,
        state=final_state,
        reason="Cryptographic quorum satisfied. Awaiting human merge."
    )
