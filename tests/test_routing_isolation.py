"""P0-1 acceptance tests: production SOC inference must never reach cloud.

Rewritten to exercise the live inference path (ModelRouter.route_with_provider
via InferenceService) after the legacy route_inference helper was removed.

Test names test_production_routing_no_cloud and test_local_outage_fail_closed
are required by verify_p0.sh and must not be renamed.
"""
import pytest
from unittest.mock import MagicMock

from engine.model_registry import (
    ModelRouter, ProviderConfig, ProviderScope,
    OpenAICompatibleProvider, LocalInferenceUnavailableError,
    get_routing_mode,
)
from engine.inference_service import InferenceService


def _make_router():
    router = ModelRouter()

    local = MagicMock(spec=OpenAICompatibleProvider)
    local.config = ProviderConfig(
        name="local-llama", scope=ProviderScope.LOCAL_SOC,
        roles=("triage", "primary", "code_review"),
        base_url="http://localhost:11434", priority=10,
    )
    local.is_healthy.return_value = True
    local.generate.return_value = "local-response"

    cloud = MagicMock(spec=OpenAICompatibleProvider)
    cloud.config = ProviderConfig(
        name="openrouter", scope=ProviderScope.DEVELOPMENT,
        roles=("triage", "primary", "code_review", "dev_triage"),
        base_url="https://openrouter.ai", priority=30,
    )
    cloud.is_healthy.return_value = True
    cloud.generate.return_value = "cloud-response"

    router.register(local)
    router.register(cloud)
    return router


def test_production_routing_no_cloud(monkeypatch):
    """Required by verify_p0.sh. Production SOC never reaches cloud."""
    monkeypatch.setenv("SOC_ROUTING_MODE", "production")
    router = _make_router()
    service = InferenceService(router)
    result = service.generate(prompt="test", role="triage", scope="soc")
    assert result.provider_id == "local-llama"
    router.providers["openrouter"].generate.assert_not_called()


def test_local_outage_fail_closed(monkeypatch):
    """Required by verify_p0.sh. Production SOC with no local provider fails closed."""
    monkeypatch.setenv("SOC_ROUTING_MODE", "production")
    router = ModelRouter()
    cloud = MagicMock(spec=OpenAICompatibleProvider)
    cloud.config = ProviderConfig(
        name="openrouter", scope=ProviderScope.DEVELOPMENT,
        roles=("triage",), base_url="https://openrouter.ai", priority=10,
    )
    cloud.is_healthy.return_value = True
    router.register(cloud)

    service = InferenceService(router)
    with pytest.raises(LocalInferenceUnavailableError):
        service.generate(prompt="test", role="triage", scope="soc")
    cloud.generate.assert_not_called()


def test_production_mode_not_inferred_from_provider(monkeypatch):
    """Production mode is deterministic, sourced from env only."""
    monkeypatch.setenv("SOC_ROUTING_MODE", "production")
    assert get_routing_mode() == "production"
    monkeypatch.setenv("SOC_ROUTING_MODE", "development")
    assert get_routing_mode() == "development"


def test_production_rejects_dev_scope(monkeypatch):
    """In production mode, scope='dev' raises before any provider is consulted."""
    monkeypatch.setenv("SOC_ROUTING_MODE", "production")
    router = _make_router()
    service = InferenceService(router)
    with pytest.raises(LocalInferenceUnavailableError):
        service.generate(prompt="test", role="dev_triage", scope="dev")
    router.providers["openrouter"].generate.assert_not_called()
    router.providers["local-llama"].generate.assert_not_called()


def test_development_mode_allows_cloud(monkeypatch):
    """In development mode, cloud providers are reachable for dev roles."""
    monkeypatch.setenv("SOC_ROUTING_MODE", "development")
    router = _make_router()
    service = InferenceService(router)
    result = service.generate(prompt="test", role="dev_triage", scope="dev")
    assert result.provider_id == "openrouter"


def test_production_triage_local_available(monkeypatch):
    """Local provider is selected for production triage when available."""
    monkeypatch.setenv("SOC_ROUTING_MODE", "production")
    router = _make_router()
    service = InferenceService(router)
    result = service.generate(prompt="test", role="triage", scope="soc")
    assert result.provider_id == "local-llama"


def test_production_never_selects_openrouter(monkeypatch):
    """Even with cloud registered first, production triage picks local."""
    monkeypatch.setenv("SOC_ROUTING_MODE", "production")
    router = _make_router()
    service = InferenceService(router)
    result = service.generate(prompt="test", role="primary", scope="soc")
    assert result.provider_id == "local-llama"
    router.providers["openrouter"].generate.assert_not_called()
