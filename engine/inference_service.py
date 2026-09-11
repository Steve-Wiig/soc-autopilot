from __future__ import annotations
import time
import logging
from dataclasses import dataclass
from engine.model_registry import ModelRouter, ProviderScope

logger = logging.getLogger(__name__)

@dataclass
class InferenceResult:
    model_id: str
    model_version: str
    provider_id: str
    raw_output: str
    latency_ms: float

class InferenceService:
    def __init__(self, router: ModelRouter, hard_timeout_s: float = 30.0):
        self.router = router
        self.hard_timeout_s = hard_timeout_s

    def generate(self, prompt: str, role: str = "triage", scope: str = "soc") -> InferenceResult:
        provider_scope = ProviderScope.LOCAL_SOC if scope == "soc" else ProviderScope.DEVELOPMENT
        start = time.time()
        try:
            raw_output, provider = self.router.route_with_provider(prompt=prompt, role=role, scope=provider_scope)
        except Exception as e:
            raise RuntimeError(f"Inference failed for scope '{scope}': {e}") from e

        latency_ms = int((time.time() - start) * 1000)
        return InferenceResult(
            model_id=provider.config.model,
            model_version="v1",
            provider_id=provider.config.name,
            raw_output=raw_output,
            latency_ms=latency_ms
        )
