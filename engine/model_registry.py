"""Model registry and routing logic for engine inference providers.

This module defines the provider abstraction (`ModelProvider`), a concrete
OpenAI-compatible HTTP provider implementation, and the `ModelRouter` that
selects among registered providers based on role/scope with a fail-closed
policy for production SOC inference.
"""

import os
import time
from enum import Enum
from typing import Dict, Tuple, Optional, Any, FrozenSet
from dataclasses import dataclass
from abc import ABC, abstractmethod
import requests
from engine.telemetry import log_attempt


class ProviderScope(str, Enum):
    """Scope classification for a provider, controlling routing eligibility."""
    LOCAL_SOC = "local_soc"
    DEVELOPMENT = "development"


class LocalInferenceUnavailableError(Exception):
    """Raised when local/edge inference is unavailable for a production SOC role.

    This is a fail_closed condition: callers must not fall back to cloud.
    """
    pass


# Roles that require a local provider to be available when running in
# production routing mode (fail_closed enforcement).
PRODUCTION_ROLES: FrozenSet[str] = frozenset({"triage", "primary", "code_review"})


def get_routing_mode() -> str:
    """Get the deterministic routing mode from the environment.

    Returns:
        One of 'production', 'development', or 'test'. Defaults to
        'production' if unset or set to an unrecognized value.
    """
    mode = os.environ.get('SOC_ROUTING_MODE', 'production').lower()
    if mode not in ('production', 'development', 'test'):
        mode = 'production'
    return mode


class InferenceTelemetry:
    """Thin wrapper around telemetry logging for inference attempts."""

    @staticmethod
    def log_attempt(
        provider: str,
        role: str,
        latency_ms: int,
        success: bool,
        failure_class: Optional[str] = None,
        attempt: int = 1,
    ) -> None:
        """Log a single inference attempt, swallowing telemetry errors.

        Args:
            provider: Name of the provider that handled (or attempted) the request.
            role: Logical role the inference was routed for (e.g. 'triage').
            latency_ms: Time taken for the attempt, in milliseconds.
            success: Whether the attempt succeeded.
            failure_class: Short identifier for the failure type, if any.
            attempt: 1-based attempt number within the current routing call.
        """
        try:
            log_attempt({
                "event_type": "inference_attempt",
                "provider": provider,
                "role": role,
                "latency_ms": latency_ms,
                "success": success,
                "failure_class": failure_class,
                "attempt_num": attempt,
            })
        except Exception as exc:
            print(f"Telemetry write failed: {exc}")


@dataclass
class ProviderConfig:
    """Static configuration describing a single model provider."""
    name: str
    roles: Tuple[str, ...]
    base_url: str
    scope: ProviderScope = ProviderScope.LOCAL_SOC
    priority: int = 50
    timeout: int = 60
    model: str = "default"
    api_key_env: str = ""


class ModelProvider(ABC):
    """Abstract base class for any inference provider."""

    @abstractmethod
    def is_healthy(self) -> bool:
        """Return whether the provider is currently reachable/healthy."""
        pass

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion for the given prompt."""
        pass


class OpenAICompatibleProvider(ModelProvider):
    """Provider implementation for any OpenAI-chat-completions-compatible API."""

    # How long a health check result is cached before re-checking.
    HEALTH_CHECK_CACHE_SECONDS: int = 30
    # Timeout used specifically for the lightweight health check request.
    HEALTH_CHECK_TIMEOUT_SECONDS: int = 5

    def __init__(self, config: ProviderConfig):
        """Initialize the provider with its static configuration."""
        self.config = config
        self._last_health_check: float = 0
        self._healthy: bool = False

    def _normalize_base_url(self) -> str:
        """Return the provider's base URL stripped of trailing slash and '/v1' suffix."""
        base = self.config.base_url.rstrip('/')
        if base.endswith('/v1'):
            base = base[:-3]
        return base

    def is_healthy(self) -> bool:
        """Check (with caching) whether the provider's API is reachable."""
        if time.time() - self._last_health_check < self.HEALTH_CHECK_CACHE_SECONDS:
            return self._healthy
        try:
            base = self._normalize_base_url()
            resp = requests.get(f"{base}/v1/models", timeout=self.HEALTH_CHECK_TIMEOUT_SECONDS)
            self._healthy = (resp.status_code == 200)
        except Exception:
            self._healthy = False
        self._last_health_check = time.time()
        return self._healthy

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Send a chat-completion request and return the response text.

        Raises:
            PermissionError: On HTTP 401/403 (authentication failure).
            ConnectionError: On HTTP 429 (quota exceeded) or 5xx (server error).
            ValueError: If the response is missing expected 'choices' data.
            requests.HTTPError: For other non-success HTTP status codes.
        """
        base = self._normalize_base_url()
        payload = {
            "model": kwargs.get("model", self.config.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.2)
        }
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            api_key = os.environ.get(self.config.api_key_env, "")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        resp = requests.post(f"{base}/v1/chat/completions", json=payload, headers=headers, timeout=self.config.timeout)

        if resp.status_code in (401, 403):
            raise PermissionError("AUTH_FAILURE")
        if resp.status_code == 429:
            raise ConnectionError("QUOTA_EXCEEDED")
        if resp.status_code >= 500:
            raise ConnectionError("SERVER_ERROR")

        resp.raise_for_status()
        data = resp.json()
        if "choices" not in data or not data["choices"]:
            raise ValueError("MALFORMED_RESPONSE")
        return data["choices"][0]["message"]["content"]


class ModelRouter:
    """Routes inference requests to the appropriate provider.

    Enforces a fail_closed policy: in production routing mode, production
    SOC roles must have a local provider available, and non-local scopes
    are rejected outright.
    """

    def __init__(self):
        """Initialize the router with an empty provider registry."""
        self.providers: Dict[str, ModelProvider] = {}

    def register(self, provider: ModelProvider) -> None:
        """Register a provider instance, keyed by its configured name."""
        self.providers[provider.config.name] = provider

    def route_with_provider(
        self,
        prompt: str,
        role: str = "triage",
        scope: ProviderScope = ProviderScope.LOCAL_SOC,
        **kwargs: Any,
    ) -> Tuple[str, ModelProvider]:
        """Route a prompt to the best available provider for role/scope.

        Args:
            prompt: The prompt text to send to the provider.
            role: Logical role requested (e.g. 'triage', 'primary', 'code_review').
            scope: Provider scope to route within (local SOC vs development).
            **kwargs: Extra generation parameters forwarded to the provider.

        Returns:
            A tuple of (generated text, provider instance that produced it).

        Raises:
            LocalInferenceUnavailableError: If production fail_closed policy
                is violated (see class docstring).
            RuntimeError: If no eligible providers exist, or all eligible
                providers failed to produce a result.
        """
        mode = get_routing_mode()

        # P0-1: fail_closed enforcement for production SOC inference.
        if mode == "production":
            if scope != ProviderScope.LOCAL_SOC:
                raise LocalInferenceUnavailableError(
                    f"scope='{scope.value}' rejected in production mode. "
                    f"Cloud/development inference requires SOC_ROUTING_MODE=development."
                )
            if role in PRODUCTION_ROLES:
                has_local = any(
                    provider.config.scope == ProviderScope.LOCAL_SOC and role in provider.config.roles
                    for provider in self.providers.values()
                )
                if not has_local:
                    raise LocalInferenceUnavailableError(
                        f"No local provider for production role='{role}'. FAIL CLOSED."
                    )

        candidates = [provider for provider in self.providers.values() if provider.config.scope == scope]
        candidates = [provider for provider in candidates if role in provider.config.roles]
        candidates.sort(key=lambda provider: provider.config.priority)

        if not candidates:
            raise RuntimeError(f"No providers available for role='{role}' and scope='{scope.value}'")

        attempt = 0
        last_exception: Optional[Exception] = None
        for provider in candidates:
            attempt += 1
            if not provider.is_healthy():
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, "OFFLINE", attempt)
                continue
            try:
                start = time.time()
                result = provider.generate(prompt, **kwargs)
                latency = int((time.time() - start) * 1000)
                InferenceTelemetry.log_attempt(provider.config.name, role, latency, True, attempt=attempt)
                return result, provider
            except PermissionError:
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, "AUTH_FAILURE", attempt)
                continue
            except Exception as exc:
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, str(type(exc).__name__), attempt)
                last_exception = exc
                continue
        raise RuntimeError(f"All providers for role '{role}' in scope '{scope.value}' failed.") from last_exception

    def route(
        self,
        prompt: str,
        role: str = "triage",
        scope: ProviderScope = ProviderScope.LOCAL_SOC,
        **kwargs: Any,
    ) -> str:
        """Route a prompt and return only the generated text.

        Convenience wrapper around `route_with_provider`.
        """
        result, _ = self.route_with_provider(prompt, role, scope, **kwargs)
        return result


def get_default_router() -> ModelRouter:
    """Build and return a `ModelRouter` pre-registered with the default providers."""
    router = ModelRouter()
    router.register(OpenAICompatibleProvider(ProviderConfig(
        name="android_qwen", scope=ProviderScope.LOCAL_SOC, roles=("triage", "code_review"),
        base_url=os.environ.get("SOC_MOCK_LLM_URL", "http://192.168.1.19:12434"), priority=10, timeout=30, model="qwen2.5-coder-1.5b-instruct-q6_k.gguf"
    )))
    router.register(OpenAICompatibleProvider(ProviderConfig(
        name="local_ollama", scope=ProviderScope.LOCAL_SOC, roles=("triage", "code_review", "primary"),
        base_url=os.environ.get("SOC_MOCK_LLM_URL", "http://localhost:11434"), priority=20, timeout=60
    )))
    router.register(OpenAICompatibleProvider(ProviderConfig(
        name="openrouter",
        scope=ProviderScope.DEVELOPMENT,
        roles=("primary", "code_review", "dev_triage"),
        base_url="https://openrouter.ai/api",
        priority=30,
        timeout=120,
        api_key_env="OPENROUTER_API_KEY",
    )))
    return router
