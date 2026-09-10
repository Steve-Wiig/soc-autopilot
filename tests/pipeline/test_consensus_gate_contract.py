import pytest

import engine.consensus_gate as consensus_gate
import overnight.llm_client as llm_client


def test_get_consensus_returns_three_values_when_both_approve(monkeypatch):
    calls = []

    def fake_generate(*args, **kwargs):
        calls.append("generate")
        return '{"approve": true, "reason": "approve-1"}'

    def fake_gemini(*args, **kwargs):
        calls.append("gemini")
        return '{"approve": true, "reason": "approve-2"}'

    # get_consensus performs local imports from overnight.llm_client.
    # Patch that actual dependency boundary, not consensus_gate globals.
    monkeypatch.setattr(llm_client, "generate", fake_generate)
    monkeypatch.setattr(llm_client, "_call_gemini", fake_gemini)

    result = consensus_gate.get_consensus(
        "harmless test proposal",
        {"gemini": "test-key"},
    )

    assert result == (
        True,
        {"approve": True, "reason": "approve-1"},
        {"approve": True, "reason": "approve-2"},
    )
    assert calls == ["generate", "gemini"]


def test_get_consensus_returns_three_values_when_votes_disagree(monkeypatch):
    calls = []

    def fake_generate(*args, **kwargs):
        calls.append("generate")
        return '{"approve": true, "reason": "approve"}'

    def fake_gemini(*args, **kwargs):
        calls.append("gemini")
        return '{"approve": false, "reason": "reject"}'

    monkeypatch.setattr(llm_client, "generate", fake_generate)
    monkeypatch.setattr(llm_client, "_call_gemini", fake_gemini)

    result = consensus_gate.get_consensus(
        "harmless test proposal",
        {"gemini": "test-key"},
    )

    assert result[0] is False
    assert result[1]["approve"] is True
    assert result[2]["approve"] is False
    assert calls == ["generate", "gemini"]


def test_get_consensus_returns_three_values_on_model_failure(monkeypatch):
    calls = []

    def fail_generate(*args, **kwargs):
        calls.append("generate")
        raise RuntimeError("simulated failure")

    def fake_gemini(*args, **kwargs):
        calls.append("gemini")
        return "not json"

    monkeypatch.setattr(llm_client, "generate", fail_generate)
    monkeypatch.setattr(llm_client, "_call_gemini", fake_gemini)

    result = consensus_gate.get_consensus(
        "harmless test proposal",
        {"gemini": "test-key"},
    )

    assert isinstance(result, tuple)
    assert len(result) == 3

    approved, vote1, vote2 = result

    assert approved is False
    assert vote1["approve"] is False
    assert "Judge 1 Error" in vote1["reason"]
    assert vote2["approve"] is False
    assert vote2["reason"].startswith("Failed to parse JSON")


def test_prohibited_proposal_never_calls_judges(monkeypatch):
    calls = []

    def called(*args, **kwargs):
        calls.append(True)
        raise AssertionError("A judge was called for a prohibited proposal")

    monkeypatch.setattr(llm_client, "generate", called)
    monkeypatch.setattr(llm_client, "_call_gemini", called)

    with pytest.raises(ValueError, match="prohibited characters"):
        consensus_gate.get_consensus(
            "unsafe; proposal -- test",
            {"gemini": "test-key"},
        )

    assert calls == []


def test_processor_and_gate_have_three_value_contract():
    gate = open("engine/consensus_gate.py", encoding="utf-8").read()
    processor = open("tools/process_oracle.py", encoding="utf-8").read()

    assert "return approved, vote1, vote2" in gate
    assert "return approved, audit_log" not in gate
    assert "approved, v1, v2 = get_consensus" in processor
