import os
import json
import tempfile
import shutil
import pytest
import threading
from pathlib import Path
from unittest.mock import patch
from engine.telemetry import TelemetryWriter

@pytest.fixture
def temp_buffer():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)

def get_sample_event(rem_id="abc123", attempt=1):
    return {
        "ts": "2026-08-30T18:50:00.123Z",
        "remediation_id": rem_id,
        "target_file": "engine/example.py",
        "issue_hash": "sha256",
        "category": "maintainability",
        "provider": "openrouter",
        "model": "nemotron-340b",
        "attempt_num": attempt,
        "gen_duration_ms": 4500,
        "syntax_valid": True,
        "attempt_outcome": "success"
    }

def test_normal_append(temp_buffer):
    writer = TelemetryWriter(temp_buffer)
    writer.log_attempt(get_sample_event())
    assert (Path(temp_buffer) / "current.jsonl").exists()
    with open(Path(temp_buffer) / "current.jsonl") as f:
        data = json.loads(f.read())
        assert data["remediation_id"] == "abc123"

def test_rotation_and_outbox(temp_buffer):
    writer = TelemetryWriter(temp_buffer, rotate_bytes=100, max_buffer_bytes=1000)
    for i in range(10):
        writer.log_attempt(get_sample_event(attempt=i))
    
    outbox = list((Path(temp_buffer) / "outbox").glob("pending_*.jsonl"))
    assert len(outbox) >= 1
    assert (Path(temp_buffer) / "current.jsonl").exists()

def test_cap_enforcement(temp_buffer):
    writer = TelemetryWriter(temp_buffer, rotate_bytes=100, max_buffer_bytes=500)
    for i in range(100):
        writer.log_attempt(get_sample_event(attempt=i))
        
    total_size = sum(f.stat().st_size for f in Path(temp_buffer).rglob("*") if f.is_file())
    assert total_size <= 500 + 100  # Allow 1 rotation margin

def test_rotation_failure_drop_mode(temp_buffer):
    writer = TelemetryWriter(temp_buffer, rotate_bytes=100, max_buffer_bytes=500)
    
    with patch('os.rename', side_effect=OSError("Mocked rename failure")):
        for i in range(50):
            writer.log_attempt(get_sample_event(attempt=i))
            
    assert writer._drop_mode is True

def test_secret_sanitization(temp_buffer):
    writer = TelemetryWriter(temp_buffer)
    event = get_sample_event()
    event["api_keys"] = {"OPENROUTER": "sk-secret-123"}
    event["prompt"] = "Fix this code"
    
    writer.log_attempt(event)
    
    with open(Path(temp_buffer) / "current.jsonl") as f:
        content = f.read()
        data = json.loads(content)
        assert "api_keys" not in data
        assert "prompt" not in data
        assert "sk-secret-123" not in content

def test_exception_isolation(temp_buffer):
    writer = TelemetryWriter(temp_buffer)
    with patch('os.open', side_effect=OSError("Mocked disk full")):
        # Must not raise
        writer.log_attempt(get_sample_event())

def test_caller_immutability(temp_buffer):
    writer = TelemetryWriter(temp_buffer)
    event = get_sample_event()
    event["api_keys"] = {"OPENROUTER": "sk-secret-123"}
    original_keys = set(event.keys())
    
    writer.log_attempt(event)
    
    assert set(event.keys()) == original_keys
    assert "api_keys" in event
    assert event["api_keys"]["OPENROUTER"] == "sk-secret-123"

def test_drop_mode_recovery(temp_buffer):
    writer = TelemetryWriter(temp_buffer, rotate_bytes=100, max_buffer_bytes=500)
    
    with patch('os.rename', side_effect=OSError("Mocked rename failure")):
        for i in range(50):
            writer.log_attempt(get_sample_event(attempt=i))
            
    assert writer._drop_mode is True
    
    current = Path(temp_buffer) / "current.jsonl"
    if current.exists():
        current.unlink()
        
    writer.log_attempt(get_sample_event(attempt=1000))
    assert writer._drop_mode is False
    assert current.exists()

def test_concurrent_writers(temp_buffer):
    writer = TelemetryWriter(temp_buffer, rotate_bytes=500, max_buffer_bytes=50000)
    
    def write_batch(start, count):
        for i in range(count):
            writer.log_attempt(get_sample_event(attempt=start+i))
            
    threads = []
    num_threads = 5
    writes_per_thread = 20
    
    for t in range(num_threads):
        th = threading.Thread(target=write_batch, args=(t * writes_per_thread, writes_per_thread))
        threads.append(th)
        th.start()
        
    for th in threads:
        th.join()
        
    total_records = 0
    for f in Path(temp_buffer).rglob("*.jsonl"):
        with open(f) as fp:
            for line in fp:
                if line.strip():
                    json.loads(line)
                    total_records += 1
                    
    assert total_records == num_threads * writes_per_thread

# ----- Phase 1: Pi telemetry tests -----
def test_log_attempt_with_extra_fields(tmpdir):
    writer = TelemetryWriter(buffer_root=tmpdir)
    writer.log_attempt({"base": "value"}, worker_type="pi", pi_latency_ms=123)
    with open(writer.current_file, 'r') as f:
        event = json.loads(f.readline())
    assert event["base"] == "value"
    assert event["worker_type"] == "pi"
    assert event["pi_latency_ms"] == 123

def test_heartbeat_event(tmpdir):
    writer = TelemetryWriter(buffer_root=tmpdir)
    writer.log_attempt({"event_type": "pi_heartbeat"}, worker_type="pi", status="idle")
    with open(writer.current_file, 'r') as f:
        event = json.loads(f.readline())
    assert event["event_type"] == "pi_heartbeat"
    assert event["worker_type"] == "pi"
    assert event["status"] == "idle"

def test_sanitization_keeps_extra_fields(tmpdir):
    writer = TelemetryWriter(buffer_root=tmpdir)
    writer.log_attempt({"api_keys": "secret"}, worker_type="pi", prompt="should be removed")
    with open(writer.current_file, 'r') as f:
        event = json.loads(f.readline())
    assert "api_keys" not in event
    assert "prompt" not in event
    assert event["worker_type"] == "pi"

def test_extra_fields_override(tmpdir):
    writer = TelemetryWriter(buffer_root=tmpdir)
    writer.log_attempt({"worker_type": "old"}, worker_type="pi")
    with open(writer.current_file, 'r') as f:
        event = json.loads(f.readline())
    assert event["worker_type"] == "pi"

def test_backward_compatibility(tmpdir):
    writer = TelemetryWriter(buffer_root=tmpdir)
    writer.log_attempt({"event": "legacy"})
    with open(writer.current_file, 'r') as f:
        event = json.loads(f.readline())
    assert event["event"] == "legacy"
# ----- end new tests -----
