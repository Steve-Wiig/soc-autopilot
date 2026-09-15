"""
End-to-end verification of the Development Orchestrator.
Proves the bridge works and enforces the PENDING_HUMAN_MERGE boundary.
"""
import pytest
from engine.development_orchestrator import run_development_cycle
from engine.aider_development_worker import AiderWorkerResult
from contracts.promotion_state import PromotionState
from contracts.worker_key_registry import WorkerKeyRegistry
from tests.helpers.crypto_test_helpers import create_signed_vote, create_test_registry

# Mock the dispatch to avoid actual Aider execution in unit tests
import engine.development_orchestrator as orch_module

def mock_dispatch_success(request):
    class MockDispatch:
        accepted_for_review = True
        backend = "aider"
        worker_result = AiderWorkerResult(
            success=True,
            changed_files=["test.py"],
            diff="diff --git a/test.py b/test.py\n+print('hello')",
            stdout="",
            stderr="",
            returncode=0,
            reason="Success",
            model_name="test-model"
        )
    return MockDispatch()

def test_orchestrator_promotes_to_pending_human_merge(monkeypatch):
    monkeypatch.setattr(orch_module, "dispatch_development_worker", mock_dispatch_success)
    
    registry = create_test_registry(["judge1", "judge2", "judge3"])
    
    # We need a dummy candidate hash to sign the votes, but the orchestrator 
    # generates the candidate internally. For this test, we'll mock the candidate 
    # creation or just use a known hash if we can intercept it.
    # Actually, let's just use the exact diff hash from the mock.
    expected_diff = "diff --git a/test.py b/test.py\n+print('hello')"
    import hashlib
    expected_hash = hashlib.sha256(expected_diff.encode("utf-8")).hexdigest()
    
    votes = [
        create_signed_vote("judge1", expected_hash, registry=registry),
        create_signed_vote("judge2", expected_hash, registry=registry),
        create_signed_vote("judge3", expected_hash, registry=registry),
    ]
    
    result = run_development_cycle(
        prompt="Fix the bug",
        allowed_files=["test.py"],
        key_registry=registry,
        judge_votes=votes
    )
    
    assert result.success is True
    assert result.state == PromotionState.PENDING_HUMAN_MERGE
    assert "Awaiting human merge" in result.reason

def test_orchestrator_rejects_on_failed_quorum(monkeypatch):
    monkeypatch.setattr(orch_module, "dispatch_development_worker", mock_dispatch_success)
    
    registry = create_test_registry(["judge1", "judge2", "judge3"])
    
    # Only 1 approval (needs 2)
    expected_diff = "diff --git a/test.py b/test.py\n+print('hello')"
    import hashlib
    expected_hash = hashlib.sha256(expected_diff.encode("utf-8")).hexdigest()
    
    votes = [
        create_signed_vote("judge1", expected_hash, decision="approve", registry=registry),
        create_signed_vote("judge2", expected_hash, decision="reject", registry=registry),
        create_signed_vote("judge3", expected_hash, decision="reject", registry=registry),
    ]
    
    result = run_development_cycle(
        prompt="Fix the bug",
        allowed_files=["test.py"],
        key_registry=registry,
        judge_votes=votes
    )
    
    assert result.success is False
    assert result.state == PromotionState.REJECTED
