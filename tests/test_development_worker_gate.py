"""Basic test suite to satisfy the autonomous swarm's commit gatekeeper."""
import pytest
from engine.development_worker_gate import evaluate_worker_quorum, WorkerApprovalVote

def test_evaluate_worker_quorum_basic():
    votes = [
        WorkerApprovalVote(judge="judge1", approve=True),
        WorkerApprovalVote(judge="judge2", approve=True),
        WorkerApprovalVote(judge="judge3", approve=False),
    ]
    decision = evaluate_worker_quorum(votes)
    assert decision.approved is True

def test_evaluate_worker_quorum_rejects_veto():
    votes = [
        WorkerApprovalVote(judge="judge1", approve=True),
        WorkerApprovalVote(judge="judge2", approve=True),
        WorkerApprovalVote(judge="judge3", approve=True),
    ]
    decision = evaluate_worker_quorum(votes, hard_vetoes=["CRITICAL_FAILURE"])
    assert decision.approved is False
