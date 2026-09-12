import pytest
from unittest.mock import patch, MagicMock
from engine.model_registry import (
    ModelRouter, ProviderConfig, ProviderScope,
    OpenAICompatibleProvider, get_default_router,
    LocalInferenceUnavailableError,
)
from engine.inference_service import InferenceService

@pytest.fixture
def mock_router():
    """Router with mocked local (primary fails, secondary succeeds) and cloud."""
    router = ModelRouter()

    local_primary = MagicMock(spec=OpenAICompatibleProvider)
    local_primary.config = ProviderConfig(
        name="local_primary", scope=ProviderScope.LOCAL_SOC,
        roles=("triage",), base_url="http://localhost:11434", priority=10,
    )
    local_primary.is_healthy.return_value = True
    local_primary.generate.side_effect = ConnectionError("Simulated local failure")

    local_secondary = MagicMock(spec=OpenAICompatibleProvider)
    local_secondary.config = ProviderConfig(
        name="local_secondary", scope=ProviderScope.LOCAL_SOC,
        roles=("triage",), base_url="http://192.168.1.19:12434", priority=20,
    )
    local_secondary.is_healthy.return_value = True
    local_secondary.generate.return_value = '{"classification": "BENIGN"}'

    cloud_provider = MagicMock(spec=OpenAICompatibleProvider)
    cloud_provider.config = ProviderConfig(
        name="openrouter", scope=ProviderScope.DEVELOPMENT,
        roles=("triage", "dev_triage"), base_url="https://openrouter.ai", priority=30,
    )
    cloud_provider.is_healthy.return_value = True

    router.register(local_primary)
    router.register(local_secondary)
    router.register(cloud_provider)
    return router


def test_soc_scope_excludes_cloud_provider(mock_router):
    """PROOF: Cloud providers are structurally unreachable for SOC triage."""
    service = InferenceService(mock_router)
    result = service.generate(prompt="test", role="triage", scope="soc")
    assert result.provider_id == "local_secondary"
    assert result.raw_output == '{"classification": "BENIGN"}'
    mock_router.providers["openrouter"].generate.assert_not_called()


def test_local_failover_on_primary_failure(mock_router):
    """PROOF: Sequential fallback works when primary local model fails."""
    service = InferenceService(mock_router)
    result = service.generate(prompt="test", role="triage", scope="soc")
    mock_router.providers["local_primary"].generate.assert_called_once()
    mock_router.providers["local_secondary"].generate.assert_called_once()


def test_all_local_down_raises_unavailable_error(mock_router):
    """PROOF: System fails closed when all local models are down."""
    mock_router.providers["local_primary"].generate.side_effect = ConnectionError("Down")
    mock_router.providers["local_secondary"].generate.side_effect = ConnectionError("Down")
    service = InferenceService(mock_router)
    with pytest.raises(RuntimeError, match="Inference failed for scope 'soc'"):
        service.generate(prompt="test", role="triage", scope="soc")
    mock_router.providers["openrouter"].generate.assert_not_called()


def test_development_scope_can_use_cloud(mock_router, monkeypatch):
    """PROOF: Cloud is accessible only when SOC_ROUTING_MODE=development."""
    monkeypatch.setenv("SOC_ROUTING_MODE", "development")
    service = InferenceService(mock_router)
    mock_router.providers["openrouter"].generate.return_value = "dev response"
    result = service.generate(prompt="test", role="dev_triage", scope="dev")
    assert result.provider_id == "openrouter"
    assert result.raw_output == "dev response"


def test_dev_scope_rejected_in_production_mode(mock_router, monkeypatch):
    """PROOF: In production mode, scope='dev' is rejected before any provider runs."""
    monkeypatch.setenv("SOC_ROUTING_MODE", "production")
    service = InferenceService(mock_router)
    with pytest.raises(LocalInferenceUnavailableError, match="rejected in production mode"):
        service.generate(prompt="test", role="dev_triage", scope="dev")
    mock_router.providers["openrouter"].generate.assert_not_called()
    mock_router.providers["local_primary"].generate.assert_not_called()
    mock_router.providers["local_secondary"].generate.assert_not_called()
