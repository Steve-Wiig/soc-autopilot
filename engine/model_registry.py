"""
Unified Model Provider Abstraction (v2 - Production Grade)
Implements true cascading failover with failure classification and telemetry.
"""
import time
import json
import requests
from abc import ABC, abstractmethod
from typing import Dict
from dataclasses import dataclass
from pathlib import Path

LEDGER_PATH = Path(__file__).parent / "inference_ledger.jsonl"

class InferenceTelemetry:
    """Observable telemetry for all inference attempts."""
    @staticmethod
    def log_attempt(provider: str, role: str, latency_ms: int, success: bool, failure_class: str = None):
        record = {
            "timestamp": time.time(),
            "provider": provider,
            "role": role,
            "latency_ms": latency_ms,
            "success": success,
            "failure_class": failure_class
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
    role: str  # "primary", "triage", "experimental"
    base_url: str
    timeout: int = 60
    model: str = "default"

class ModelProvider(ABC):
    @abstractmethod
    def is_healthy(self) -> bool: pass
    
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str: pass

class OpenAICompatibleProvider(ModelProvider):
    """Handles Ollama, llama.cpp, vLLM, and OpenAI-compatible endpoints."""
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._last_health_check = 0
        self._healthy = False

    def is_healthy(self) -> bool:
        if time.time() - self._last_health_check < 30:
            return self._healthy
        try:
            resp = requests.get(f"{self.config.base_url}/v1/models", timeout=5)
            self._healthy = (resp.status_code == 200)
        except Exception:
            self._healthy = False
        self._last_health_check = time.time()
        return self._healthy

    def generate(self, prompt: str, **kwargs) -> str:
        """Generates response. Failure classification happens here, telemetry in Router."""
        payload = {
            "model": kwargs.get("model", self.config.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.2)
        }
        resp = requests.post(f"{self.config.base_url}/v1/chat/completions", 
                             json=payload, timeout=self.config.timeout)
        
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
        """True cascading failover with centralized telemetry."""
        candidates = [p for p in self.providers.values() if p.config.role == role]
        
        for provider in candidates:
            if not provider.is_healthy():
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, "OFFLINE")
                continue
                
            try:
                start = time.time()
                result = provider.generate(prompt, **kwargs)
                latency = int((time.time() - start) * 1000)
                
                # Centralized success logging
                InferenceTelemetry.log_attempt(provider.config.name, role, latency, True)
                return result
                
            except PermissionError:
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, "AUTH_FAILURE")
                continue
            except Exception as e:
                # Timeout, Quota, Server Error, Malformed - log and move to next
                InferenceTelemetry.log_attempt(provider.config.name, role, 0, False, str(type(e).__name__))
                continue
                
        raise RuntimeError(f"All providers for role '{role}' failed or offline.")

# --- Bootstrap Default Providers ---
def get_default_router() -> ModelRouter:
    router = ModelRouter()
    
    # Cloud Providers (Primary)
    router.register(OpenAICompatibleProvider(ProviderConfig("openrouter", "primary", "https://openrouter.ai/api/v1", 120)))
    
    # Edge Providers (Triage/Experimental)
    router.register(OpenAICompatibleProvider(ProviderConfig("android_qwen", "triage", "http://192.168.1.19:12434", 30, "qwen2.5-coder-1.5b-instruct-q6_k.gguf")))
    router.register(OpenAICompatibleProvider(ProviderConfig("local_ollama", "triage", "http://localhost:11434", 60)))
    
    return router
