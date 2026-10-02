"""Service layer responsible for routing prompts to inference providers.

This module wraps :class:`ModelRouter` with a small, typed facade
(`InferenceService`) that callers use to run inference requests, while
preserving safety guarantees such as the P0-1 local-inference guard.
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass
from typing import Literal
from engine.model_registry import (
    ModelRouter, ProviderScope, LocalInferenceUnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass
class InferenceResult:
    """Outcome of a single inference request.

    Attributes:
        model_id: Identifier of the model that produced the output.
        model_version: Version string of the model used.
        provider_id: Identifier of the provider that served the request.
        raw_output: The raw text returned by the model.
        latency_ms: Wall-clock time taken to obtain the result, in milliseconds.
    """
    model_id: str
    model_version: str
    provider_id: str
    raw_output: str
    latency_ms: int


class InferenceService:
    """High-level entry point for running inference requests.

    Delegates the actual provider selection to a :class:`ModelRouter` and
    converts its output into a normalized :class:`InferenceResult`.
    """

    def __init__(self, router: ModelRouter, hard_timeout_s: float = 30.0):
        """Initialize the service.

        Args:
            router: The router used to select and invoke an inference provider.
            hard_timeout_s: Upper bound, in seconds, that a single inference
                call is allowed to take. Currently informational; enforcement
                is expected to happen within the router/provider layer.
        """
        self.router = router
        self.hard_timeout_s = hard_timeout_s

    def generate(
        self,
        prompt: str,
        role: Literal["triage"] | str = "triage",
        scope: Literal["soc", "development"] | str = "soc",
    ) -> InferenceResult:
        """Run an inference request and return a normalized result.

        Args:
            prompt: The prompt text to send to the model.
            role: Logical role used by the router to pick an appropriate model.
            scope: Deployment scope; `"soc"` maps to local SOC-only providers,
                anything else maps to development providers.

        Returns:
            An :class:`InferenceResult` describing the model, provider, raw
            output, and latency of the request.

        Raises:
            LocalInferenceUnavailableError: Propagated verbatim from the
                router so callers can distinguish a policy rejection (P0-1
                safety guard) from a transient provider failure.
            RuntimeError: Raised for any other failure encountered while
                routing or invoking the provider.
        """
        # "soc" scope is restricted to local-only providers (P0-1 safety guard);
        # any other scope value falls back to the development provider pool.
        provider_scope = ProviderScope.LOCAL_SOC if scope == "soc" else ProviderScope.DEVELOPMENT

        start_time = time.time()
        try:
            raw_output, provider = self.router.route_with_provider(
                prompt=prompt, role=role, scope=provider_scope,
            )
        except LocalInferenceUnavailableError:
            # P0-1 safety guard — propagate verbatim so callers can distinguish
            # a policy rejection from a transient provider failure.
            raise
        except Exception as exc:
            raise RuntimeError(f"Inference failed for scope '{scope}': {exc}") from exc

        latency_ms = int((time.time() - start_time) * 1000)
        return InferenceResult(
            model_id=provider.config.model,
            model_version="v1",
            provider_id=provider.config.name,
            raw_output=raw_output,
            latency_ms=latency_ms,
        )
