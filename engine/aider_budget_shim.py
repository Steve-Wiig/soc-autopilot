"""Trusted Aider/LiteLLM cloud-budget enforcement shim.

Loaded as Python sitecustomize inside the disposable Aider sandbox.

Cloud models must obtain an atomic reservation from the parent budget broker
before LiteLLM is allowed to make the external request.

Local Ollama models bypass the cloud budget.
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any
import litellm


_SOCKET_ENV = "AIDER_BUDGET_SOCKET"

_METADATA_BLOCKED_HOSTS = frozenset({
    "raw.githubusercontent.com",
})

_METADATA_ALLOWED_OPENROUTER_PREFIX = "/api/"


def _is_blocked_metadata_url(url: object) -> bool:
    """Return True if `url` points at a metadata endpoint that must be blocked.

    Metadata endpoints are informational/model-listing calls (e.g. Aider's
    legacy OpenRouter model-page lookup) that are distinct from the actual
    provider API calls, which must remain reachable.
    """
    if not isinstance(url, str) or not url:
        return False

    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
    except Exception:
        return False

    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if host in _METADATA_BLOCKED_HOSTS:
        return True

    # Aider's legacy OpenRouter model-page lookup is metadata, while
    # /api/... is the actual provider API and must remain reachable.
    if host == "openrouter.ai":
        return not path.startswith(_METADATA_ALLOWED_OPENROUTER_PREFIX)

    return False


def _install_metadata_network_gate() -> None:
    """Monkeypatch `requests.Session.request` to block metadata URL calls.

    Idempotent: safe to call multiple times, the patch is only applied once
    per process.
    """
    import requests

    if getattr(requests, "_soc_autopilot_metadata_gate_installed", False):
        return

    original_request = requests.sessions.Session.request

    def guarded_request(
        self: "requests.sessions.Session",
        method: str,
        url: Any,
        *args: Any,
        **kwargs: Any,
    ) -> "requests.Response":
        """Delegate to the original `request`, blocking metadata URLs first."""
        if _is_blocked_metadata_url(url):
            raise RuntimeError(
                "Aider metadata network request blocked by SOC-AUTOPILOT: "
                + str(url)
            )
        return original_request(
            self,
            method,
            url,
            *args,
            **kwargs,
        )

    requests.sessions.Session.request = guarded_request
    requests._soc_autopilot_metadata_gate_installed = True


def _provider_for_model(model: str) -> str | None:
    """Return the cloud provider name for `model`, or None if it is local."""
    if model.startswith("openrouter/"):
        return "openrouter"
    if model.startswith("gemini/"):
        return "gemini"
    return None


def _reserve(provider: str, model: str) -> None:
    """Request an atomic budget reservation from the parent broker.

    Connects to the Unix socket named by the `AIDER_BUDGET_SOCKET`
    environment variable, sends a reservation request, and raises
    `RuntimeError` unless the broker confirms the reservation.
    """
    socket_path = os.environ.get(_SOCKET_ENV, "").strip()

    # Cloud execution MUST have the broker.
    if not socket_path:
        raise RuntimeError(
            f"Aider cloud request blocked: {_SOCKET_ENV} is not configured"
        )

    reservation_payload = {
        "op": "reserve",
        "provider": provider,
        "model": model,
    }

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5.0)
            sock.connect(socket_path)
            sock.sendall(
                (json.dumps(reservation_payload, separators=(",", ":")) + "\n").encode()
            )

            data = b""
            while b"\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
    except OSError as exc:
        raise RuntimeError(
            f"Aider cloud request blocked: budget broker unavailable: {type(exc).__name__}"
        ) from exc

    if not data:
        raise RuntimeError("Aider cloud request blocked: empty broker response")

    try:
        response = json.loads(data.split(b"\n", 1)[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Aider cloud request blocked: malformed broker response") from exc

    if response.get("ok") is not True:
        raise RuntimeError(
            f"Aider cloud request blocked: broker error={response.get('error', 'UNKNOWN')}"
        )

    if response.get("reserved") is not True:
        raise RuntimeError(
            f"Aider cloud request blocked: {response.get('reason', 'BUDGET_DENIED')}"
        )


def install() -> None:
    """Install the metadata network gate and the LiteLLM budget-enforcing shim.

    Idempotent: safe to call multiple times, each patch is only applied once
    per process.
    """
    _install_metadata_network_gate()

    if getattr(litellm, "_soc_autopilot_budget_shim_installed", False):
        return

    original_completion = litellm.completion

    def guarded_completion(*args: Any, **kwargs: Any) -> Any:
        """Reserve cloud budget (if needed) before delegating to LiteLLM."""
        model = kwargs.get("model")

        if not isinstance(model, str) or not model:
            raise RuntimeError(
                "Aider cloud request blocked: LiteLLM model is missing"
            )

        provider = _provider_for_model(model)

        # Local models are intentionally outside cloud API accounting.
        if provider is not None:
            _reserve(provider, model)

        return original_completion(*args, **kwargs)

    litellm.completion = guarded_completion
    litellm._soc_autopilot_budget_shim_installed = True


install()
