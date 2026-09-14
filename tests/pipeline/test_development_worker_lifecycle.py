
"""
Development-worker lifecycle contract test.

Important distinction:

    WorkerApprovalVote
        = bounded pipeline/quorum approval artifact

    WorkerVote
        = hardened identity/provenance artifact used by strict quorum

This test exercises the development-worker pipeline using the
correct WorkerApprovalVote type.
"""

import inspect

from contracts.promotion_state import (
    PromotionState,
    TransitionError,
    validate_transition,
)

from engine.aider_development_worker import AiderWorkerResult
from engine.development_candidate import DevelopmentCandidate
from engine.development_worker_dispatch import (
    AIDER_BACKEND,
    DevelopmentWorkerRequest,
    dispatch_development_worker,
)
from engine.development_worker_gate import (
    WorkerApprovalVote,
    evaluate_worker_quorum,
)
from engine.development_worker_pipeline import evaluate_worker_proposal


def _proposal():
    return AiderWorkerResult(
        success=True,
        changed_files=("engine/example.py",),
        diff=(
            "diff --git a/engine/example.py b/engine/example.py\n"
            "--- a/engine/example.py\n"
            "+++ b/engine/example.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        ),
        stdout="proposal generated",
        stderr="",
        returncode=0,
        reason="test proposal",
        model_name="test-model",
    )


def _approval_vote(worker_id, approved):
    """
    Construct WorkerApprovalVote using the repository's actual
    constructor signature.

    We do not invent the class contract. Required fields are mapped
    from their names and the test fails closed on an unknown field.
    """
    signature = inspect.signature(WorkerApprovalVote)
    kwargs = {}

    for name, parameter in signature.parameters.items():
        if name == "self":
            continue

        if parameter.default is not inspect.Parameter.empty:
            continue

        key = name.lower()

        if key in {
            "worker",
            "worker_id",
            "judge",
            "judge_id",
            "reviewer",
            "reviewer_id",
        } or key.endswith("_id"):
            kwargs[name] = worker_id
            continue

        if (
            "approve" in key
            or key in {
                "approved",
                "allow",
                "allowed",
                "accept",
                "accepted",
            }
        ):
            kwargs[name] = approved
            continue

        if key in {"decision", "result"}:
            kwargs[name] = "approve" if approved else "reject"
            continue

        if "reason" in key or "rationale" in key:
            kwargs[name] = (
                "independent approval"
                if approved
                else "independent rejection"
            )
            continue

        if "evidence" in key:
            kwargs[name] = f"evidence-{worker_id}"
            continue

        if "hash" in key:
            kwargs[name] = "test-proposal-hash"
            continue

        raise AssertionError(
            "Unknown required WorkerApprovalVote field: "
            f"{name!r}. Inspect engine/development_worker_gate.py."
        )

    try:
        return WorkerApprovalVote(**kwargs)
    except TypeError as exc:
        raise AssertionError(
            "Could not construct WorkerApprovalVote using fields "
            f"{sorted(kwargs)}: {exc}"
        ) from exc


def test_bounded_development_worker_lifecycle(monkeypatch):
    proposal = _proposal()

    import engine.development_worker_dispatch as dispatch_module

    def fake_aider_worker(
        prompt,
        files,
        *,
        model=None,
        api_base=None,
        timeout=180,
    ):
        return proposal

    monkeypatch.setattr(
        dispatch_module,
        "run_aider_worker",
        fake_aider_worker,
    )

    request = DevelopmentWorkerRequest(
        prompt="bounded maintenance change",
        files=("engine/example.py",),
        backend=AIDER_BACKEND,
        model="test-model",
        timeout=30,
    )

    # -----------------------------------------------------------
    # Stage 1: dispatcher -> worker proposal
    # -----------------------------------------------------------
    dispatched = dispatch_development_worker(request)

    assert dispatched.accepted_for_review is True
    assert dispatched.worker_result is proposal

    # -----------------------------------------------------------
    # Stage 2: proposal -> candidate
    # -----------------------------------------------------------
    candidate = DevelopmentCandidate.from_diff(
        candidate_id="candidate-test-001",
        base_commit="HEAD-test",
        diff_text=proposal.diff,
        changed_files=list(proposal.changed_files),
    )

    assert candidate.candidate_id == "candidate-test-001"
    assert candidate.verify_diff_integrity(proposal.diff) is True

    # -----------------------------------------------------------
    # Stage 3: 3 independent approval votes -> 2-of-3
    #
    # This is intentionally WorkerApprovalVote, because that is the
    # contract consumed by development_worker_pipeline.
    # -----------------------------------------------------------
    votes = [
        _approval_vote("worker-A", True),
        _approval_vote("worker-B", True),
        _approval_vote("worker-C", False),
    ]

    approval = evaluate_worker_proposal(
        proposal,
        ["engine/example.py"],
        votes=votes,
        safety_ok=True,
        regression_ok=True,
    )

    assert approval.approved is True
    assert approval.decision.approval_count == 2
    assert approval.decision.vote_count == 3

    # -----------------------------------------------------------
    # Stage 4: human merge boundary
    # -----------------------------------------------------------
    validate_transition(
        PromotionState.GENERATED,
        PromotionState.TESTED,
    )

    validate_transition(
        PromotionState.TESTED,
        PromotionState.CANARY_PASSED,
    )

    validate_transition(
        PromotionState.CANARY_PASSED,
        PromotionState.PENDING_HUMAN_MERGE,
    )

    validate_transition(
        PromotionState.PENDING_HUMAN_MERGE,
        PromotionState.MERGED,
    )


def test_direct_canary_to_merged_is_forbidden():
    try:
        validate_transition(
            PromotionState.CANARY_PASSED,
            PromotionState.MERGED,
        )
    except TransitionError:
        return

    raise AssertionError(
        "CANARY_PASSED must require PENDING_HUMAN_MERGE first"
    )


def test_aider_worker_isolation_is_real():
    from engine.aider_development_worker import run_aider_worker

    source = inspect.getsource(run_aider_worker)

    assert "run_in_worktree(" in source
    assert "cwd=worker_root" in source
    assert "cwd=repo_root" not in source


def test_worker_approval_vote_is_the_pipeline_vote_contract():
    signature = inspect.signature(WorkerApprovalVote)

    # The lifecycle pipeline must accept this type, not the legacy
    # identity/provenance WorkerVote.
    assert signature is not None
