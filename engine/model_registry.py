"""
Unified Model Provider Abstraction.
Routes requests to Cloud, Local GPU, or Edge nodes (e.g., Android Qwen).
"""
import time
import requests
from abc import ABC, abstractmethod
from typing import Optional, Dict, List
from dataclasses import dataclass

@dataclass
class ProviderConfig:
    name: str
    role: str  # "primary", "triage", "experimental"
    base_url: str
    timeout: int = 60

class ModelProvider(ABC):
    @abstractmethod
    def is_healthy(self) -> bool: pass
    
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str: pass

class OpenAICompatibleProvider(ModelProvider):
    """Handles Ollama, llama.cpp, and vLLM endpoints."""
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._last_health_check = 0
        self._healthy = False

    def is_healthy(self) -> bool:
        if time.time() - self._last_health_check < 30:
            return self._healthy
        try:
            # Standard OpenAI-compatible health check
            resp = requests.get(f"{self.config.base_url}/v1/models", timeout=5)
            self._healthy = resp.status_code == 200
        except Exception:
            self._healthy = False
        self._last_health_check = time.time()
        return self._healthy

    def generate(self, prompt: str, **kwargs) -> str:
        if not self.is_healthy():
            raise RuntimeError(f"Provider {self.config.name} is offline")
        
        payload = {
            "model": kwargs.get("model", "default"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.2)
        }
        resp = requests.post(f"{self.config.base_url}/v1/chat/completions", 
                             json=payload, timeout=self.config.timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

class ModelRouter:
    def __init__(self):
        self.providers: Dict[str, ModelProvider] = {}
        
    def register(self, provider: ModelProvider):
        self.providers[provider.config.name] = provider
        
    def route(self, prompt: str, role: str = "triage", **kwargs) -> str:
        """Routes to the first healthy provider matching the requested role."""
        candidates = [p for p in self.providers.values() if p.config.role == role]
        for provider in candidates:
            if provider.is_healthy():
                try:
                    return provider.generate(prompt, **kwargs)
                except Exception as e:
                    print(f"⚠️ Provider {provider.config.name} failed: {e}")
        raise RuntimeError(f"No healthy providers available for role: {role}")
