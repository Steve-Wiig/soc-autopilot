import os
import time
from enum import Enum
from typing import Dict, Tuple
from dataclasses import dataclass
from abc import ABC, abstractmethod
import requests
from engine.telemetry import log_attempt

class ProviderScope(str, Enum):
    LOCAL_SOC = "local_soc"
    DEVELOPMENT = "development"

class InferenceTelemetry:
    @staticmethod
    def log_attempt(provider: str, role: str, latency_ms: int, success: bool, failure_class: str = None, attempt: int = 1):
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
        except Exception as e:
            print(f"Telemetry write failed: {e}")

@dataclass
class ProviderConfig:
    name: str
    roles: Tuple[str, ...]
    base_url: str
    scope: ProviderScope = ProviderScope.LOCAL_SOC
    priority: int = 50
    timeout: int = 60
    model: str = "default"
    api_key_env: str = ""

class ModelProvider(ABC):
    @abstractmethod
    def is_healthy(self) -> bool: pass

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str: pass

class OpenAICompatibleProvider(ModelProvider):
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._last_health_check = 0
        self._healthy = False

    def _normalize_base_url(self) -> str:
        base = self.config.base_url.rstrip('/')
        if base.endswith('/v1'):
            base = base[:-3]
        return base

    def is_healthy(self) -> bool:
        if time.time() - self._last_health_check < 30:
            return self._healthy
        try:
            base = self._normalize_base_url()
            resp = requests.get(f"{base}/v1/models", timeout=5)
            self._healthy = (resp.status_code == 200)
        except Exception:
            self._healthy = False
        self._last_health_check = time.time()
        return self._healthy

    def generate(self, prompt: str, **kwargs) -> str:
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
    def __init__(self):
        self.providers: Dict[str, ModelProvider] = {}

    def register(self, provider: ModelProvider):
        self.providers[provider.config.name] = provider

    def route_with_provider(self, prompt: str, role: str = "triage", scope: ProviderScope = ProviderScope.LOCAL_SOC, **kwargs) -> Tuple[str, ModelProvider]:
        candidates = [p for p in self.providers.values() if p.config.scope == scope]
        candidates = [p for p in candidates if role in p.config.roles]
        candidates.sort(key=lambda p: p.config.priority)

        if not candidates:
            raise RuntimeError(f"No providers available for role='{role}' and scope='{scope.value}'")

        attempt = 0
        last_exception = None
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
            except Exception as e:
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, str(type(e).__name__), attempt)
                last_exception = e
                continue
        raise RuntimeError(f"All providers for role '{role}' in scope '{scope.value}' failed.") from last_exception

    def route(self, prompt: str, role: str = "triage", scope: ProviderScope = ProviderScope.LOCAL_SOC, **kwargs) -> str:
        result, _ = self.route_with_provider(prompt, role, scope, **kwargs)
        return result

def get_default_router() -> ModelRouter:
    router = ModelRouter()
    router.register(OpenAICompatibleProvider(ProviderConfig(
        name="android_qwen", scope=ProviderScope.LOCAL_SOC, roles=("triage", "code_review"),
        base_url="http://192.168.1.19:12434", priority=10, timeout=30, model="qwen2.5-coder-1.5b-instruct-q6_k.gguf"
    )))
    router.register(OpenAICompatibleProvider(ProviderConfig(
        name="local_ollama", scope=ProviderScope.LOCAL_SOC, roles=("triage", "code_review", "primary"),
        base_url="http://localhost:11434", priority=20, timeout=60
    )))
    router.register(OpenAICompatibleProvider(ProviderConfig(
        name="openrouter", scope=ProviderScope.DEVELOPMENT, roles=("primary", "code_review", "dev_triage"),
        base_url="https://openrouter.ai/api", priority=30, timeout=120, api_key_env="OPENROUTER_API_KEY"
    )))
    return router
