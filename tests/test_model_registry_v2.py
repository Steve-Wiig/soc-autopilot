import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from engine.model_registry import get_default_router, OpenAICompatibleProvider, ProviderConfig, LEDGER_PATH

def test_cascading_failover_and_telemetry():
    # Clear ledger
    if LEDGER_PATH.exists():
        LEDGER_PATH.unlink()
        
    router = get_default_router()
    
    # Mock the Android node as "healthy" but returning a malformed response
    android = router.providers["android_qwen"]
    local = router.providers["local_ollama"]
    
    with patch.object(android, 'is_healthy', return_value=True), \
         patch.object(local, 'is_healthy', return_value=True), \
         patch.object(android, 'generate', side_effect=ValueError("MALFORMED_RESPONSE")), \
         patch.object(local, 'generate', return_value="Verdict: Safe") as mock_local:
         
        # Route should skip the broken Android node and succeed on Local
        result = router.route("Analyze this log", role="triage")
        
        assert result == "Verdict: Safe"
        mock_local.assert_called_once()
        
        # Verify Telemetry Ledger
        assert LEDGER_PATH.exists()
        logs = [json.loads(line) for line in LEDGER_PATH.read_text().splitlines()]
        
        assert len(logs) == 2
        assert logs[0]["provider"] == "android_qwen"
        assert logs[0]["success"] is False
        assert logs[0]["failure_class"] == "ValueError"
        
        assert logs[1]["provider"] == "local_ollama"
        assert logs[1]["success"] is True
        
        print("✅ PROVEN: True cascading failover works. Malformed Android response skipped, routed to Local, and logged to telemetry ledger.")

if __name__ == "__main__":
    test_cascading_failover_and_telemetry()
