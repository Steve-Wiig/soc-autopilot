from engine.aider_development_worker import AiderWorkerResult
from engine.development_worker_gate import WorkerVote
from engine.development_worker_pipeline import evaluate_worker_proposal


def worker_result(*files):
    return AiderWorkerResult(
        success=True,
        changed_files=tuple(files),
        diff="diff --git ...",
        stdout="",
        stderr="",
        returncode=0,
        reason="ok",
    )


def approval_votes(*approvals):
    return [
        WorkerVote(
            judge=f"judge-{idx}",
            approve=approved,
            reason="test vote",
        )
        for idx, approved in enumerate(approvals, 1)
    ]


def evaluate(result, votes, safety_ok=True, regression_ok=True):
    return evaluate_worker_proposal(
        result,
        ["engine/example.py"],
        votes=votes,
        safety_ok=safety_ok,
        regression_ok=regression_ok,
    )


def test_two_of_three_approves_when_hard_gates_pass():
    result = worker_result("engine/example.py")

    decision = evaluate(
        result,
        approval_votes(True, True, False),
    )

    assert decision.approved is True
    assert decision.decision.approval_count == 2
    assert decision.decision.vote_count == 3
    assert decision.hard_vetoes == ()


def test_three_of_three_approves():
    result = worker_result("engine/example.py")

    decision = evaluate(
        result,
        approval_votes(True, True, True),
    )

    assert decision.approved is True
    assert decision.decision.approval_count == 3


def test_one_of_three_rejects():
    result = worker_result("engine/example.py")

    decision = evaluate(
        result,
        approval_votes(True, False, False),
    )

    assert decision.approved is False
    assert decision.decision.approval_count == 1


def test_zero_of_three_rejects():
    result = worker_result("engine/example.py")

    decision = evaluate(
        result,
        approval_votes(False, False, False),
    )

    assert decision.approved is False
    assert decision.decision.approval_count == 0


def test_empty_worker_change_is_hard_rejection():
    result = worker_result()

    decision = evaluate(
        result,
        approval_votes(True, True, True),
    )

    assert decision.approved is False
    assert "no changed files" in " ".join(
        decision.hard_vetoes
    ).lower()


def test_unauthorized_path_is_hard_rejection():
    result = worker_result(
        "engine/example.py",
        "path/to/unauthorized.py",
    )

    decision = evaluate(
        result,
        approval_votes(True, True, True),
    )

    assert decision.approved is False
    assert any(
        "unauthorized worker paths" in veto.lower()
        for veto in decision.hard_vetoes
    )


def test_safety_veto_overrides_unanimous_approval():
    result = worker_result("engine/example.py")

    decision = evaluate(
        result,
        approval_votes(True, True, True),
        safety_ok=False,
    )

    assert decision.approved is False
    assert decision.decision.approval_count == 3


def test_regression_veto_overrides_unanimous_approval():
    result = worker_result("engine/example.py")

    decision = evaluate(
        result,
        approval_votes(True, True, True),
        regression_ok=False,
    )

    assert decision.approved is False
    assert decision.decision.approval_count == 3


def test_failed_worker_cannot_approve():
    result = AiderWorkerResult(
        success=False,
        changed_files=("engine/example.py",),
        diff="",
        stdout="",
        stderr="",
        returncode=124,
        reason="worker timeout",
    )

    decision = evaluate(
        result,
        approval_votes(True, True, True),
    )

    assert decision.approved is False
    assert any(
        "worker failed" in veto.lower()
        for veto in decision.hard_vetoes
    )


def test_quorum_votes_remain_independent_from_hard_gates():
    result = worker_result("engine/example.py")

    decision = evaluate(
        result,
        approval_votes(True, True, False),
    )

    assert decision.decision.approval_count == 2
    assert decision.decision.required_approvals == 2
    assert decision.decision.required_votes == 3
    assert decision.approved is True
