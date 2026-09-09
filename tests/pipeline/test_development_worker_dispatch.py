from engine.aider_development_worker import AiderWorkerResult
from engine.development_worker_dispatch import (
    AIDER_BACKEND,
    LEGACY_BACKEND,
    DevelopmentWorkerRequest,
    dispatch_development_worker,
)


def fake_legacy_worker(request):
    return {
        "kind": "legacy-proposal",
        "files": request.files,
    }


def test_legacy_backend_is_default():
    request = DevelopmentWorkerRequest(
        prompt="do work",
        files=("engine/example.py",),
    )

    result = dispatch_development_worker(
        request,
        legacy_worker=fake_legacy_worker,
    )

    assert result.backend == LEGACY_BACKEND
    assert result.accepted_for_review is True
    assert result.worker_result["kind"] == "legacy-proposal"


def test_explicit_legacy_backend():
    request = DevelopmentWorkerRequest(
        prompt="do work",
        files=("engine/example.py",),
        backend=LEGACY_BACKEND,
    )

    result = dispatch_development_worker(
        request,
        legacy_worker=fake_legacy_worker,
    )

    assert result.backend == LEGACY_BACKEND
    assert result.accepted_for_review is True


def test_aider_backend_uses_worker_result():
    expected = AiderWorkerResult(
        success=True,
        changed_files=("engine/example.py",),
        diff="diff --git ...",
        stdout="",
        stderr="",
        returncode=0,
        reason="proposal",
    )

    request = DevelopmentWorkerRequest(
        prompt="do work",
        files=("engine/example.py",),
        backend=AIDER_BACKEND,
    )

    def fake_aider(prompt, files, **kwargs):
        assert prompt == "do work"
        assert files == ("engine/example.py",)
        return expected

    from unittest.mock import patch

    with patch(
        "engine.development_worker_dispatch.run_aider_worker",
        side_effect=fake_aider,
    ):
        result = dispatch_development_worker(request)

    assert result.backend == AIDER_BACKEND
    assert result.accepted_for_review is True
    assert result.worker_result is expected


def test_failed_aider_is_not_accepted():
    failed = AiderWorkerResult(
        success=False,
        changed_files=("engine/example.py",),
        diff="",
        stdout="",
        stderr="",
        returncode=124,
        reason="timeout",
    )

    request = DevelopmentWorkerRequest(
        prompt="do work",
        files=("engine/example.py",),
        backend=AIDER_BACKEND,
    )

    from unittest.mock import patch

    with patch(
        "engine.development_worker_dispatch.run_aider_worker",
        return_value=failed,
    ):
        result = dispatch_development_worker(request)

    assert result.backend == AIDER_BACKEND
    assert result.accepted_for_review is False
    assert "timeout" in result.reason


def test_unsupported_backend_rejected():
    request = DevelopmentWorkerRequest(
        prompt="do work",
        files=("engine/example.py",),
        backend="not-a-real-backend",
    )

    result = dispatch_development_worker(request)

    assert result.accepted_for_review is False
    assert "unsupported" in result.reason.lower()


def test_legacy_failure_is_not_accepted():
    def failing_worker(request):
        raise RuntimeError("synthetic failure")

    request = DevelopmentWorkerRequest(
        prompt="do work",
        files=("engine/example.py",),
        backend=LEGACY_BACKEND,
    )

    result = dispatch_development_worker(
        request,
        legacy_worker=failing_worker,
    )

    assert result.accepted_for_review is False
    assert "legacy worker failed" in result.reason.lower()


def test_dispatcher_does_not_equate_proposal_with_approval():
    expected = AiderWorkerResult(
        success=True,
        changed_files=("engine/example.py",),
        diff="diff --git ...",
        stdout="",
        stderr="",
        returncode=0,
        reason="proposal",
    )

    request = DevelopmentWorkerRequest(
        prompt="do work",
        files=("engine/example.py",),
        backend=AIDER_BACKEND,
    )

    from unittest.mock import patch

    with patch(
        "engine.development_worker_dispatch.run_aider_worker",
        return_value=expected,
    ):
        result = dispatch_development_worker(request)

    # Worker success means only that a proposal exists.
    # Approval belongs to the separate quorum/gate pipeline.
    assert result.accepted_for_review is True
    assert not hasattr(result, "approved")
