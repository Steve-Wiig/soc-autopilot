"""
Development-worker dispatcher.

Default backend:
    legacy

Optional backend:
    aider

The dispatcher is intentionally separate from self_improver.py for the
first integration checkpoint.

Policy:
- Legacy remains the default.
- Aider requires explicit opt-in.
- Aider remains a worker only.
- The worker result is never treated as approval.
- Quorum, deterministic gates, tests, canary, and Git governance stay outside.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Sequence

from engine.aider_development_worker import (
    AiderWorkerResult,
    run_aider_worker,
)
from engine.aider_provider import CLOUD_ENABLE_ENV, resolve_aider_providers


LEGACY_BACKEND = "legacy"
AIDER_BACKEND = "aider"
DEFAULT_BACKEND = LEGACY_BACKEND


@dataclass(frozen=True)
class DevelopmentWorkerRequest:
    prompt: str
    files: tuple[str, ...]
    backend: str = DEFAULT_BACKEND
    model: str | None = None
    api_base: str | None = None
    timeout: int = 180


@dataclass(frozen=True)
class DevelopmentWorkerDispatchResult:
    backend: str
    accepted_for_review: bool
    worker_result: Any
    reason: str


def _configured_backend() -> str:
    value = os.getenv(
        "SOC_AUTOPILOT_DEVELOPMENT_WORKER",
        DEFAULT_BACKEND,
    ).strip().lower()

    if value not in {LEGACY_BACKEND, AIDER_BACKEND}:
        return DEFAULT_BACKEND

    return value


def _aider_failure_allows_provider_fallback(
    result: AiderWorkerResult,
) -> bool:
    """Return True only for failures plausibly caused by the provider path."""

    if result.success:
        return False

    # Never retry after a worker-boundary/safety decision.
    terminal_markers = (
        "unauthorized paths",
        "modified git history",
        "no working-tree change",
        "no diff was produced",
        "could not verify worker head",
    )

    text = " ".join(
        (
            result.reason,
            result.stdout,
            result.stderr,
        )
    ).lower()

    # Worker-level provider classification is authoritative for fallback.
    # It intentionally overrides generic "no working-tree change" text.
    if (
        "provider/inference failure observed" in text
        or "provider failure observed" in text
    ):
        return True

    if any(marker in text for marker in terminal_markers):
        return False

    if result.returncode == 124:
        return True

    provider_markers = (
        "401",
        "403",
        "429",
        "authentication",
        "unauthorized",
        "forbidden",
        "rate limit",
        "rate-limit",
        "quota",
        "budget exhausted",
        "budget denied",
        "provider unavailable",
        "service unavailable",
        "connection",
        "connecterror",
        "connectionerror",
        "timed out",
        "timeout",
        "model not found",
        "does not exist",
        "api error",
        "api request",
        "cloud request blocked",
        "budget broker unavailable",
        "budget control failure",
    )

    return result.returncode != 0 and any(
        marker in text for marker in provider_markers
    )


def _explicit_aider_kwargs(
    request: DevelopmentWorkerRequest,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "timeout": request.timeout,
    }

    if request.model:
        kwargs["model"] = request.model

    if request.api_base:
        kwargs["api_base"] = request.api_base

    return kwargs


def dispatch_development_worker(
    request: DevelopmentWorkerRequest,
    *,
    legacy_worker: Callable[[DevelopmentWorkerRequest], Any] | None = None,
) -> DevelopmentWorkerDispatchResult:
    """
    Dispatch a bounded implementation request.

    `accepted_for_review` means only that the selected worker returned a
    proposal object. It does NOT mean that the proposal is approved.
    """

    backend = (
        request.backend.strip().lower()
        if request.backend
        else _configured_backend()
    )

    if backend == LEGACY_BACKEND:
        if legacy_worker is None:
            return DevelopmentWorkerDispatchResult(
                backend=LEGACY_BACKEND,
                accepted_for_review=False,
                worker_result=None,
                reason="Legacy worker callback was not supplied.",
            )

        try:
            result = legacy_worker(request)
        except Exception as exc:
            return DevelopmentWorkerDispatchResult(
                backend=LEGACY_BACKEND,
                accepted_for_review=False,
                worker_result=None,
                reason=f"Legacy worker failed: {exc}",
            )

        return DevelopmentWorkerDispatchResult(
            backend=LEGACY_BACKEND,
            accepted_for_review=result is not None,
            worker_result=result,
            reason=(
                "Legacy worker produced a proposal."
                if result is not None
                else "Legacy worker produced no proposal."
            ),
        )

    if backend == AIDER_BACKEND:
        # Cloud Aider is explicitly opt-in. The resolver enforces this for
        # normal provider selection; explicit overrides must obey the same
        # kill switch.
        explicit_model = request.model or ""
        explicit_cloud = explicit_model.startswith(("openrouter/", "gemini/"))

        if explicit_cloud:
            enabled = os.environ.get(CLOUD_ENABLE_ENV, "").strip().lower() in {
                "1", "true", "yes", "on"
            }
            if not enabled:
                return DevelopmentWorkerDispatchResult(
                    backend=AIDER_BACKEND,
                    accepted_for_review=False,
                    worker_result=None,
                    reason="Cloud Aider development is disabled by policy.",
                )

        # Explicit model/base overrides retain the existing single-attempt
        # behavior. Provider rotation applies only to the resolver defaults.
        if request.model or request.api_base:
            try:
                result: AiderWorkerResult = run_aider_worker(
                    request.prompt,
                    request.files,
                    **_explicit_aider_kwargs(request),
                )
            except Exception as exc:
                return DevelopmentWorkerDispatchResult(
                    backend=AIDER_BACKEND,
                    accepted_for_review=False,
                    worker_result=None,
                    reason=f"Aider worker failed: {exc}",
                )

            return DevelopmentWorkerDispatchResult(
                backend=AIDER_BACKEND,
                accepted_for_review=result.success,
                worker_result=result,
                reason=(
                    "Aider produced a proposal."
                    if result.success
                    else (
                        "Aider proposal rejected by worker boundary: "
                        + result.reason
                    )
                ),
            )

        providers = resolve_aider_providers()

        if not providers:
            return DevelopmentWorkerDispatchResult(
                backend=AIDER_BACKEND,
                accepted_for_review=False,
                worker_result=None,
                reason="No eligible cloud Aider provider is available.",
            )

        last_result: AiderWorkerResult | None = None
        attempted: list[str] = []

        for provider in providers:
            attempted.append(provider.name)

            try:
                result = run_aider_worker(
                    request.prompt,
                    request.files,
                    model=provider.model,
                    api_base=provider.api_base,
                    timeout=request.timeout,
                    provider_name=provider.name,
                    api_key_env=provider.api_key_env,
                )
            except Exception as exc:
                # Resolver-selected providers must fail closed. Treat only
                # infrastructure-like exceptions as fallback candidates.
                result = AiderWorkerResult(
                    success=False,
                    changed_files=(),
                    diff="",
                    stdout="",
                    stderr=str(exc),
                    returncode=125,
                    reason=f"Provider attempt failed: {exc}",
                    model_name=provider.model,
                )

            last_result = result

            if result.success:
                return DevelopmentWorkerDispatchResult(
                    backend=AIDER_BACKEND,
                    accepted_for_review=True,
                    worker_result=result,
                    reason=(
                        "Aider produced a proposal using "
                        + provider.name
                        + "."
                    ),
                )

            if not _aider_failure_allows_provider_fallback(result):
                return DevelopmentWorkerDispatchResult(
                    backend=AIDER_BACKEND,
                    accepted_for_review=False,
                    worker_result=result,
                    reason=(
                        "Aider provider attempt failed at a terminal "
                        "worker/safety boundary: "
                        + result.reason
                    ),
                )

        assert last_result is not None

        return DevelopmentWorkerDispatchResult(
            backend=AIDER_BACKEND,
            accepted_for_review=False,
            worker_result=last_result,
            reason=(
                "All eligible Aider providers failed: "
                + ", ".join(attempted)
                + ". Last failure: "
                + last_result.reason
            ),
        )

    return DevelopmentWorkerDispatchResult(
        backend=backend,
        accepted_for_review=False,
        worker_result=None,
        reason=f"Unsupported development-worker backend: {backend}",
    )
