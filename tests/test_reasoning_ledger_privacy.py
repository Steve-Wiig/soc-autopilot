import json
from pathlib import Path

from engine.reasoning_ledger import record_interaction


def test_reasoning_ledger_private_by_default(tmp_path, monkeypatch):

    monkeypatch.setattr(
        "engine.reasoning_ledger.BUFFER_DIR",
        tmp_path
    )

    monkeypatch.delenv(
        "SOC_REASONING_DEBUG",
        raising=False
    )

    record_interaction(
        "test",
        "SECRET_API_KEY=abc123",
        "generated response"
    )

    event = json.loads(
        (tmp_path / "current.jsonl").read_text()
    )

    assert "prompt_preview" not in event
    assert "response_preview" not in event

    assert "abc123" not in json.dumps(event)

    assert "prompt_hash" in event
    assert "response_hash" in event


def test_reasoning_debug_preview(monkeypatch, tmp_path):

    monkeypatch.setattr(
        "engine.reasoning_ledger.BUFFER_DIR",
        tmp_path
    )

    monkeypatch.setenv(
        "SOC_REASONING_DEBUG",
        "true"
    )

    record_interaction(
        "test",
        "hello",
        "world"
    )

    event = json.loads(
        (tmp_path / "current.jsonl").read_text()
    )

    assert event["prompt_preview"] == "hello"
    assert event["response_preview"] == "world"
