"""
Unified Model Provider Abstraction (v3 - Priority Routing)
Implements true cascading failover with priority queues, role-based filtering,
URL normalization, and authentication header support.
"""
import os
import time
import json
import requests
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple
from dataclasses import dataclass, field
from pathlib import Path

LEDGER_PATH = Path(__file__).parent / "inference_ledger.jsonl"

class InferenceTelemetry:
    """Observable telemetry for all inference attempts."""
    @staticmethod
    def log_attempt(provider: str, role: str, latency_ms: int, success: bool, failure_class: str = None, attempt: int = 1):
        record = {
            "timestamp": time.time(),
            "provider": provider,
            "role": role,
            "latency_ms": latency_ms,
            "success": success,
            "failure_class": failure_class,
            "attempt": attempt
        }
        try:
            LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LEDGER_PATH, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"⚠️ Telemetry write failed: {e}")

@dataclass
class ProviderConfig:
    name: str
    roles: Tuple[str, ...]  # e.g., ("triage", "code_review")
    base_url: str
    priority: int = 50      # Lower number = higher priority (10=Edge, 20=Local, 30=Cloud)
    timeout: int = 60
    model: str = "default"
    api_key_env: str = ""   # Environment variable name for API key

class ModelProvider(ABC):
    @abstractmethod
    def is_healthy(self) -> bool: pass
    
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str: pass

class OpenAICompatibleProvider(ModelProvider):
    """Handles Ollama, llama.cpp, vLLM, OpenRouter, and OpenAI-compatible endpoints."""
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._last_health_check = 0
        self._healthy = False

    def _normalize_base_url(self) -> str:
        """Strip trailing slashes and /v1 to prevent double-path bugs."""
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
        """Generates response. Failure classification happens here, telemetry in Router."""
        base = self._normalize_base_url()
        
        payload = {
            "model": kwargs.get("model", self.config.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.2)
        }
        
        # Build headers with optional authentication
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            api_key = os.environ.get(self.config.api_key_env, "")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        
        resp = requests.post(
            f"{base}/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=self.config.timeout
        )

        # Failure Classification
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
        
    def route(self, prompt: str, role: str = "triage", **kwargs) -> str:
        """
        Priority-based cascading failover.
        Filters providers by requested role, sorts by priority (lowest first),
        and cascades through them until one succeeds.
        """
        # 1. Filter by role
        candidates = [p for p in self.providers.values() if role in p.config.roles]
        
        # 2. Sort by priority (Edge -> Local -> Cloud)
        candidates.sort(key=lambda p: p.config.priority)
        
        attempt = 0
        for provider in candidates:
            attempt += 1
            if not provider.is_healthy():
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, "OFFLINE", attempt)
                continue
                
            try:
                start = time.time()
                result = provider.generate(prompt, **kwargs)
                latency = int((time.time() - start) * 1000)
                
                # Centralized success logging
                InferenceTelemetry.log_attempt(provider.config.name, role, latency, True, attempt=attempt)
                return result
                
            except PermissionError:
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, "AUTH_FAILURE", attempt)
                continue
            except Exception as e:
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, str(type(e).__name__), attempt)
                continue
                
        raise RuntimeError(f"All providers for role '{role}' failed or offline.")

# --- Bootstrap Default Providers ---
def get_default_router() -> ModelRouter:
    router = ModelRouter()
    
    # Edge Provider (Priority 10) - Fast, local, no auth
    router.register(OpenAICompatibleProvider(
        ProviderConfig(
            name="android_qwen",
            roles=("triage", "code_review"),
            base_url="http://192.168.1.19:12434",
            priority=10,
            timeout=30,
            model="qwen2.5-coder-1.5b-instruct-q6_k.gguf"
        )
    ))
    
    # Local GPU Provider (Priority 20) - Medium speed, local, no auth
    router.register(OpenAICompatibleProvider(
        ProviderConfig(
            name="local_ollama",
            roles=("triage", "code_review", "primary"),
            base_url="http://localhost:11434",
            priority=20,
            timeout=60
        )
    ))
    
    # Cloud Provider (Priority 30) - High capability, authenticated
    router.register(OpenAICompatibleProvider(
        ProviderConfig(
            name="openrouter",
            roles=("primary", "triage", "code_review"),
            base_url="https://openrouter.ai/api",
            priority=30,
            timeout=120,
            api_key_env="OPENROUTER_API_KEY"
        )
    ))
    
    return router
