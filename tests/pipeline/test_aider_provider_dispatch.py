from engine.aider_development_worker import AiderWorkerResult
from engine.aider_provider import CLOUD_ENABLE_ENV
from engine.development_worker_dispatch import (
    AIDER_BACKEND,
    DevelopmentWorkerRequest,
    dispatch_development_worker,
)


def _result(
    *,
    success: bool,
    returncode: int,
    reason: str,
    model: str,
    stderr: str = "",
):
    return AiderWorkerResult(
        success=success,
        changed_files=("engine/example.py",) if success else (),
        diff="diff --git a/engine/example.py b/engine/example.py\n",
        stdout="",
        stderr=stderr,
        returncode=returncode,
        reason=reason,
        model_name=model,
    )


def test_default_aider_rotation_openrouter_to_gemini_to_local(
    monkeypatch,
):
    monkeypatch.setenv(CLOUD_ENABLE_ENV, "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "redacted")
    monkeypatch.setenv("GEMINI_API_KEY", "redacted")

    attempts = []

    def fake_worker(prompt, files, **kwargs):
        attempts.append(kwargs)
        provider = kwargs["provider_name"]

        if provider == "openrouter":
            return _result(
                success=False,
                returncode=1,
                reason="Aider exited with provider authentication error.",
                model=kwargs["model"],
                stderr="HTTP 401 authentication failed",
            )

        if provider == "gemini":
            return _result(
                success=False,
                returncode=1,
                reason="Aider exited with provider rate limit.",
                model=kwargs["model"],
                stderr="HTTP 429 quota exceeded",
            )

        return _result(
            success=True,
            returncode=0,
            reason="Aider produced proposal.",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        "engine.development_worker_dispatch.run_aider_worker",
        fake_worker,
    )

    result = dispatch_development_worker(
        DevelopmentWorkerRequest(
            prompt="bounded maintenance task",
            files=("engine/example.py",),
            backend=AIDER_BACKEND,
        )
    )

    assert result.accepted_for_review is True
    assert result.worker_result.success is True
    assert [x["provider_name"] for x in attempts] == [
        "openrouter",
        "gemini",
        "local_ollama",
    ]


def test_terminal_worker_failure_does_not_fallback(
    monkeypatch,
):
    monkeypatch.setenv(CLOUD_ENABLE_ENV, "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "redacted")
    monkeypatch.setenv("GEMINI_API_KEY", "redacted")

    attempts = []

    def fake_worker(prompt, files, **kwargs):
        attempts.append(kwargs)
        return _result(
            success=False,
            returncode=0,
            reason="Aider modified unauthorized paths: README.md",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        "engine.development_worker_dispatch.run_aider_worker",
        fake_worker,
    )

    result = dispatch_development_worker(
        DevelopmentWorkerRequest(
            prompt="bounded maintenance task",
            files=("engine/example.py",),
            backend=AIDER_BACKEND,
        )
    )

    assert result.accepted_for_review is False
    assert len(attempts) == 1
    assert attempts[0]["provider_name"] == "openrouter"


def test_cloud_disabled_uses_local_only(
    monkeypatch,
):
    monkeypatch.delenv(CLOUD_ENABLE_ENV, raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    attempts = []

    def fake_worker(prompt, files, **kwargs):
        attempts.append(kwargs)
        return _result(
            success=True,
            returncode=0,
            reason="Aider produced proposal.",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        "engine.development_worker_dispatch.run_aider_worker",
        fake_worker,
    )

    result = dispatch_development_worker(
        DevelopmentWorkerRequest(
            prompt="local maintenance task",
            files=("engine/example.py",),
            backend=AIDER_BACKEND,
        )
    )

    assert result.accepted_for_review is True
    assert len(attempts) == 1
    assert attempts[0]["provider_name"] == "local_ollama"
    assert attempts[0]["api_key_env"] is None


def test_explicit_model_does_not_rotate_providers(
    monkeypatch,
):
    monkeypatch.setenv("SOC_AUTOPILOT_DEVELOPMENT_CLOUD", "1")
    monkeypatch.setenv("SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY", "0")

    attempts = []

    def fake_worker(prompt, files, **kwargs):
        attempts.append(kwargs)
        return _result(
            success=False,
            returncode=1,
            reason="HTTP 401 authentication failed",
            model=kwargs["model"],
            stderr="401",
        )

    monkeypatch.setattr(
        "engine.development_worker_dispatch.run_aider_worker",
        fake_worker,
    )

    result = dispatch_development_worker(
        DevelopmentWorkerRequest(
            prompt="explicit provider task",
            files=("engine/example.py",),
            backend=AIDER_BACKEND,
            model="openrouter/custom/model",
            api_base="https://openrouter.ai/api/v1",
        )
    )

    assert result.accepted_for_review is False
    assert len(attempts) == 1
    assert attempts[0]["model"] == "openrouter/custom/model"
    assert "provider_name" not in attempts[0]

def test_zero_exit_provider_failure_falls_through_to_next_provider(
    monkeypatch,
):
    monkeypatch.setenv(CLOUD_ENABLE_ENV, "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "redacted")
    monkeypatch.setenv("GEMINI_API_KEY", "redacted")

    attempts = []

    def fake_worker(prompt, files, **kwargs):
        attempts.append(kwargs)

        if kwargs["provider_name"] == "openrouter":
            return _result(
                success=False,
                returncode=0,
                reason=(
                    "Aider provider/inference failure observed "
                    "without a working-tree change: "
                    "litellm.APIError provider unavailable"
                ),
                model=kwargs["model"],
            )

        return _result(
            success=True,
            returncode=0,
            reason="Aider produced proposal.",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        "engine.development_worker_dispatch.run_aider_worker",
        fake_worker,
    )

    result = dispatch_development_worker(
        DevelopmentWorkerRequest(
            prompt="bounded maintenance task",
            files=("engine/example.py",),
            backend=AIDER_BACKEND,
        )
    )

    assert result.accepted_for_review is True
    assert result.worker_result.success is True

    assert [item["provider_name"] for item in attempts] == [
        "openrouter",
        "gemini",
    ]

def test_explicit_provider_failure_classification_overrides_no_change_marker():
    result = _result(
        success=False,
        returncode=0,
        reason=(
            "Aider provider/inference failure observed "
            "without a working-tree change: "
            "litellm.APIError provider unavailable"
        ),
        model="openrouter/example:free",
    )

    from engine.development_worker_dispatch import (
        _aider_failure_allows_provider_fallback,
    )

    assert _aider_failure_allows_provider_fallback(result) is True

def test_genuine_no_change_does_not_fallback(
    monkeypatch,
):
    monkeypatch.setenv(CLOUD_ENABLE_ENV, "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "redacted")
    monkeypatch.setenv("GEMINI_API_KEY", "redacted")

    attempts = []

    def fake_worker(prompt, files, **kwargs):
        attempts.append(kwargs)

        return _result(
            success=False,
            returncode=0,
            reason="Aider completed but produced no working-tree change.",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        "engine.development_worker_dispatch.run_aider_worker",
        fake_worker,
    )

    result = dispatch_development_worker(
        DevelopmentWorkerRequest(
            prompt="bounded maintenance task",
            files=("engine/example.py",),
            backend=AIDER_BACKEND,
        )
    )

    assert result.accepted_for_review is False
    assert result.worker_result.success is False
    assert len(attempts) == 1
    assert attempts[0]["provider_name"] == "openrouter"

