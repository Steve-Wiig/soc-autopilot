
from engine.openrouter_catalog import (
    free_models,
    free_only_enabled,
    is_free_model,
    select_free_coding_model,
)


def _model(model_id, prompt="0", completion="0", *, inputs=("text",), outputs=("text",)):
    return {
        "id": model_id,
        "name": model_id,
        "context_length": 32768,
        "architecture": {
            "input_modalities": list(inputs),
            "output_modalities": list(outputs),
        },
        "supported_parameters": ["temperature"],
        "pricing": {
            "prompt": prompt,
            "completion": completion,
            "request": "0",
        },
    }


def test_zero_pricing_is_free():
    assert is_free_model(
        _model("example/free")
    )


def test_nonzero_pricing_is_not_free():
    assert not is_free_model(
        _model("example/paid", completion="0.000001")
    )


def test_non_text_free_model_is_filtered():
    models = [
        _model(
            "example/image-free",
            inputs=("image",),
            outputs=("image",),
        )
    ]

    assert free_models(models) == []


def test_paid_model_cannot_enter_free_pool():
    models = [
        _model("example/free"),
        _model("example/paid", prompt="0.000001"),
    ]

    result = free_models(models)

    assert [model.model_id for model in result] == ["example/free"]


def test_coding_model_is_preferred():
    models = [
        _model("example/general-free"),
        _model("example/coder-free"),
    ]

    selected = select_free_coding_model(models)

    assert selected.model_id == "example/coder-free"


def test_free_selection_is_deterministic():
    models = [
        _model("zeta/free",),
        _model("alpha/free",),
    ]

    first = select_free_coding_model(models)
    second = select_free_coding_model(models)

    assert first.model_id == second.model_id

def test_free_only_policy_can_use_explicit_environment():
    assert free_only_enabled({"SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "1"})
    assert not free_only_enabled({"SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "0"})
    assert not free_only_enabled({"SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY": "off"})

