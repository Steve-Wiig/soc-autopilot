import pytest
from unittest.mock import patch, MagicMock
from engine.model_registry import ModelRouter, OpenAICompatibleProvider, ProviderConfig

def test_edge_node_routing_and_failover():
    router = ModelRouter()
    
    # Register a "dead" primary node and a "healthy" edge node
    dead_config = ProviderConfig("dead_gpu", "triage", "http://localhost:9999")
    edge_config = ProviderConfig("android_qwen", "triage", "http://192.168.1.19:12434")
    
    dead_node = OpenAICompatibleProvider(dead_config)
    edge_node = OpenAICompatibleProvider(edge_config)
    
    router.register(dead_node)
    router.register(edge_node)
    
    # Mock the health checks and generation
    with patch.object(dead_node, 'is_healthy', return_value=False), \
         patch.object(edge_node, 'is_healthy', return_value=True), \
         patch.object(edge_node, 'generate', return_value="Verdict: Safe") as mock_gen:
        
        result = router.route("Analyze this log", role="triage", model="qwen1.5b")
        
        assert result == "Verdict: Safe"
        mock_gen.assert_called_once()
        print("✅ PROVEN: Router correctly bypassed dead node and routed to Edge node.")
