from engine.aider_provider import (
    CLOUD_ENABLE_ENV,
    resolve_aider_providers,
)


def test_local_only_is_default():
    providers = resolve_aider_providers(environ={})

    assert providers == ()


def test_cloud_order_is_openrouter_then_gemini_then_local(monkeypatch):
    import engine.aider_provider as provider

    fake_catalog = [
        {
            "id": "example/free-coder",
            "name": "Free Coder",
            "context_length": 32768,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["temperature"],
            "pricing": {
                "prompt": "0",
                "completion": "0",
                "request": "0",
            },
        },
        {
            "id": "example/paid-coder",
            "name": "Paid Coder",
            "context_length": 32768,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["temperature"],
            "pricing": {
                "prompt": "0.000001",
                "completion": "0.000002",
                "request": "0",
            },
        },
    ]

    monkeypatch.setattr(
        provider,
        "get_catalog",
        lambda **_: fake_catalog,
    )

    providers = resolve_aider_providers(
        environ={
            CLOUD_ENABLE_ENV: "1",
            "SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "1",
            "OPENROUTER_API_KEY": "redacted-openrouter",
            "GEMINI_API_KEY": "redacted-gemini",
        }
    )

    assert [p.name for p in providers] == [
        "openrouter",
        "gemini",
    ]

    assert providers[0].model == "openrouter/example/free-coder"
    assert providers[0].api_key_env == "OPENROUTER_API_KEY"

    assert providers[1].model == "gemini/gemini-3.8-flash"
    assert providers[1].api_key_env == "GEMINI_API_KEY"


def test_cloud_enabled_but_missing_keys_returns_no_providers():
    providers = resolve_aider_providers(
        environ={
            CLOUD_ENABLE_ENV: "true",
        }
    )

    assert providers == ()


def test_custom_models_are_supported():
    providers = resolve_aider_providers(
        environ={
            CLOUD_ENABLE_ENV: "yes",
            "SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "0",
            "OPENROUTER_API_KEY": "redacted",
            "GEMINI_API_KEY": "redacted",
            "AIDER_OPENROUTER_MODEL": "openrouter/custom/model",
            "AIDER_GEMINI_MODEL": "gemini/custom",
            "AIDER_LOCAL_MODEL": "ollama_chat/custom:4b",
            "AIDER_LOCAL_API_BASE": "http://127.0.0.1:9999",
        }
    )

    assert providers[0].model == "openrouter/custom/model"
    assert providers[1].model == "gemini/custom"
    assert len(providers) == 2

def test_openrouter_free_only_selects_dynamic_free_model(monkeypatch):
    import engine.aider_provider as provider

    fake_catalog = [
        {
            "id": "example/paid-coder",
            "name": "Paid Coder",
            "context_length": 32768,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["temperature"],
            "pricing": {
                "prompt": "0.000001",
                "completion": "0.000002",
            },
        },
        {
            "id": "example/free-coder",
            "name": "Free Coder",
            "context_length": 32768,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["temperature"],
            "pricing": {
                "prompt": "0",
                "completion": "0",
            },
        },
    ]

    monkeypatch.setattr(provider, "get_catalog", lambda **_: fake_catalog)

    resolved = provider.resolve_aider_providers(
        environ={
            "SOC_AUTOPILOT_DEVELOPMENT_CLOUD": "1",
            "SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "1",
            "OPENROUTER_API_KEY": "test-key",
        }
    )

    assert resolved[0].name == "openrouter"
    assert resolved[0].model == "openrouter/example/free-coder"
    assert all(
        item.model != "example/paid-coder"
        for item in resolved
    )


def test_openrouter_free_only_rejects_explicit_paid_model(monkeypatch):
    import engine.aider_provider as provider

    fake_catalog = [
        {
            "id": "example/free-coder",
            "name": "Free Coder",
            "context_length": 32768,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["temperature"],
            "pricing": {
                "prompt": "0",
                "completion": "0",
            },
        }
    ]

    monkeypatch.setattr(provider, "get_catalog", lambda **_: fake_catalog)

    resolved = provider.resolve_aider_providers(
        environ={
            "SOC_AUTOPILOT_DEVELOPMENT_CLOUD": "1",
            "SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "1",
            "OPENROUTER_API_KEY": "test-key",
            "AIDER_OPENROUTER_MODEL": "example/paid-coder",
        }
    )

    assert resolved == ()
    assert all(item.name != "openrouter" for item in resolved)


def test_openrouter_free_only_fails_closed_on_catalog_error(monkeypatch):
    import engine.aider_provider as provider

    def fail_catalog(**_):
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(provider, "get_catalog", fail_catalog)

    resolved = provider.resolve_aider_providers(
        environ={
            "SOC_AUTOPILOT_DEVELOPMENT_CLOUD": "1",
            "SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "1",
            "OPENROUTER_API_KEY": "test-key",
        }
    )

    assert all(item.name != "openrouter" for item in resolved)
    assert resolved == ()

def test_openrouter_free_model_gets_openrouter_litellm_prefix(monkeypatch):
    import engine.aider_provider as provider

    fake_catalog = [
        {
            "id": "cohere/north-mini-code:free",
            "name": "Cohere North Mini Code (free)",
            "context_length": 256000,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["temperature"],
            "pricing": {
                "prompt": "0",
                "completion": "0",
            },
        }
    ]

    monkeypatch.setattr(
        provider,
        "get_catalog",
        lambda **_: fake_catalog,
    )

    resolved = provider.resolve_aider_providers(
        environ={
            "SOC_AUTOPILOT_DEVELOPMENT_CLOUD": "1",
            "SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "1",
            "OPENROUTER_API_KEY": "test-key",
        }
    )

    assert resolved[0].model == (
        "openrouter/cohere/north-mini-code:free"
    )


def test_explicit_free_model_is_normalized_to_openrouter_prefix(monkeypatch):
    import engine.aider_provider as provider

    fake_catalog = [
        {
            "id": "cohere/north-mini-code:free",
            "name": "Cohere North Mini Code (free)",
            "context_length": 256000,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["temperature"],
            "pricing": {
                "prompt": "0",
                "completion": "0",
            },
        }
    ]

    monkeypatch.setattr(
        provider,
        "get_catalog",
        lambda **_: fake_catalog,
    )

    resolved = provider.resolve_aider_providers(
        environ={
            "SOC_AUTOPILOT_DEVELOPMENT_CLOUD": "1",
            "SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "1",
            "OPENROUTER_API_KEY": "test-key",
            "AIDER_OPENROUTER_MODEL": "cohere/north-mini-code:free",
        }
    )

    assert resolved[0].model == (
        "openrouter/cohere/north-mini-code:free"
    )

