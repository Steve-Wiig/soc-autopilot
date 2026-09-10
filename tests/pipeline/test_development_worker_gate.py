from engine.development_worker_gate import (
    REQUIRED_APPROVALS,
    REQUIRED_VOTES,
    QuorumDecision,
    WorkerVote,
    evaluate_worker_quorum,
)


def votes(*approvals):
    return [
        WorkerVote(judge=f"judge-{idx}", approve=approved)
        for idx, approved in enumerate(approvals, 1)
    ]


def test_two_of_three_approves():
    decision = evaluate_worker_quorum(votes(True, True, False))

    assert isinstance(decision, QuorumDecision)
    assert decision.approved is True
    assert decision.approval_count == 2
    assert decision.vote_count == REQUIRED_VOTES
    assert decision.required_approvals == REQUIRED_APPROVALS


def test_three_of_three_approves():
    decision = evaluate_worker_quorum(votes(True, True, True))

    assert decision.approved is True
    assert decision.approval_count == 3


def test_one_of_three_rejects():
    decision = evaluate_worker_quorum(votes(True, False, False))

    assert decision.approved is False
    assert decision.approval_count == 1


def test_zero_of_three_rejects():
    decision = evaluate_worker_quorum(votes(False, False, False))

    assert decision.approved is False
    assert decision.approval_count == 0


def test_hard_safety_veto_overrides_unanimous_approval():
    decision = evaluate_worker_quorum(
        votes(True, True, True),
        hard_vetoes=["AST safety gate failed"],
    )

    assert decision.approved is False
    assert decision.approval_count == 3
    assert decision.hard_vetoes == ("AST safety gate failed",)


def test_missing_vote_cannot_pass():
    decision = evaluate_worker_quorum(votes(True, True))

    assert decision.approved is False
    assert decision.vote_count == 2


def test_four_votes_cannot_pass():
    decision = evaluate_worker_quorum(votes(True, True, True, True))

    assert decision.approved is False
    assert decision.vote_count == 4


def test_duplicate_judges_cannot_pass():
    decision = evaluate_worker_quorum(
        [
            WorkerVote("judge-a", True),
            WorkerVote("judge-a", True),
            WorkerVote("judge-b", True),
        ]
    )

    assert decision.approved is False


def test_empty_judge_identity_cannot_pass():
    decision = evaluate_worker_quorum(
        [
            WorkerVote("", True),
            WorkerVote("judge-b", True),
            WorkerVote("judge-c", True),
        ]
    )

    assert decision.approved is False
