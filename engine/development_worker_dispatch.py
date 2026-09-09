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
        kwargs: dict[str, Any] = {
            "timeout": request.timeout,
        }

        if request.model:
            kwargs["model"] = request.model

        if request.api_base:
            kwargs["api_base"] = request.api_base

        try:
            result: AiderWorkerResult = run_aider_worker(
                request.prompt,
                request.files,
                **kwargs,
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
                else f"Aider proposal rejected by worker boundary: {result.reason}"
            ),
        )

    return DevelopmentWorkerDispatchResult(
        backend=backend,
        accepted_for_review=False,
        worker_result=None,
        reason=f"Unsupported development-worker backend: {backend}",
    )
