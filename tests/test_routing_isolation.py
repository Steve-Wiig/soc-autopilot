import pytest
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_production_triage_local_available():
    """Production triage with local available -> uses local."""
    from engine.model_registry import route_inference
    os.environ['SOC_ROUTING_MODE'] = 'production'
    
    providers = [
        {'name': 'local-llama', 'type': 'local'},
        {'name': 'openrouter', 'type': 'cloud'}
    ]
    
    result = route_inference('triage', providers)
    assert result['name'] == 'local-llama'

def test_production_triage_local_unavailable_fail_closed():
    """Production triage with local unavailable -> FAIL CLOSED."""
    from engine.model_registry import route_inference, LocalInferenceUnavailableError
    os.environ['SOC_ROUTING_MODE'] = 'production'
    
    providers = [
        {'name': 'openrouter', 'type': 'cloud'}
    ]
    
    with pytest.raises(LocalInferenceUnavailableError, match="FAIL CLOSED"):
        route_inference('triage', providers)

def test_production_edge_unavailable_fail_closed():
    """Production with edge+local unavailable -> FAIL CLOSED."""
    from engine.model_registry import route_inference, LocalInferenceUnavailableError
    os.environ['SOC_ROUTING_MODE'] = 'production'
    
    providers = [
        {'name': 'openrouter', 'type': 'cloud'},
        {'name': 'gemini', 'type': 'cloud'}
    ]
    
    with pytest.raises(LocalInferenceUnavailableError, match="FAIL CLOSED"):
        route_inference('primary', providers)

def test_development_code_review_cloud_allowed():
    """Development code_review can use cloud."""
    from engine.model_registry import route_inference
    os.environ['SOC_ROUTING_MODE'] = 'development'
    
    providers = [
        {'name': 'openrouter', 'type': 'cloud'}
    ]
    
    result = route_inference('code_review', providers)
    assert result['name'] == 'openrouter'

def test_production_mode_not_inferred_from_provider():
    """Production mode is deterministic, not inferred from providers."""
    from engine.model_registry import get_routing_mode
    os.environ['SOC_ROUTING_MODE'] = 'production'
    
    assert get_routing_mode() == 'production'
    
    os.environ['SOC_ROUTING_MODE'] = 'development'
    assert get_routing_mode() == 'development'

def test_production_never_selects_openrouter():
    """Production triage/primary never selects OpenRouter even if listed first."""
    from engine.model_registry import route_inference
    os.environ['SOC_ROUTING_MODE'] = 'production'
    
    providers = [
        {'name': 'openrouter', 'type': 'cloud'},
        {'name': 'local-llama', 'type': 'local'}
    ]
    
    result = route_inference('triage', providers)
    assert result['name'] == 'local-llama'
    assert result['type'] == 'local'

# Required names for verification harness
def test_production_routing_no_cloud():
    """Alias: production routing never reaches cloud."""
    test_production_never_selects_openrouter()

def test_local_outage_fail_closed():
    """Alias: local outage triggers fail closed."""
    test_production_triage_local_unavailable_fail_closed()
