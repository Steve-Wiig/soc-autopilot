"""Development-only Aider provider selection.

This module is intentionally separate from the SOC ModelRouter.

Trust boundary:
    - Production SOC inference remains LOCAL_SOC only.
    - These providers are for bounded development-worker execution.
    - Cloud development requires explicit opt-in.
    - OpenRouter development is free-tier-only by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
import os

from engine.openrouter_catalog import (
    free_models,
    free_only_enabled,
    get_catalog,
    select_free_coding_model,
)


DEFAULT_GEMINI_MODEL = "gemini/gemini-3.8-flash"

# Environment variable that must be truthy to allow any cloud
# (non-local) development provider to be considered at all.
CLOUD_ENABLE_ENV = "SOC_AUTOPILOT_DEVELOPMENT_CLOUD"

# Environment variable used to request a specific OpenRouter model.
OPENROUTER_MODEL_ENV = "AIDER_OPENROUTER_MODEL"


@dataclass(frozen=True)
class AiderProvider:
    """A resolved, ready-to-use development inference provider.

    Attributes:
        name: Human-readable provider identifier (e.g. "openrouter").
        model: The LiteLLM-style model reference to use for this provider.
        api_base: Base URL for the provider's API.
        api_key_env: Name of the environment variable holding the API key,
            if any.
    """

    name: str
    model: str
    api_base: str
    api_key_env: str | None = None


def _cloud_enabled(env: Mapping[str, str]) -> bool:
    """Return True when cloud development providers are explicitly enabled."""

    return env.get(CLOUD_ENABLE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _openrouter_model_ref(model_id: str) -> str:
    """Return the LiteLLM model reference for an OpenRouter model."""

    if model_id.startswith("openrouter/"):
        return model_id

    return f"openrouter/{model_id}"


def _select_openrouter_model(env: Mapping[str, str]) -> str | None:
    """Resolve an OpenRouter model without permitting paid inference.

    When free-only mode is enabled, the OpenRouter catalog is authoritative.
    A configured model must exist in the current free catalog; otherwise the
    resolver selects a currently-free coding-capable model dynamically.

    Catalog failures fail closed for OpenRouter rather than falling back to
    an unknown or potentially-paid model.
    """

    api_key = env.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None

    requested = env.get(OPENROUTER_MODEL_ENV, "").strip()

    # Free-only mode is catalog-authoritative and fails closed.
    if free_only_enabled(env):
        try:
            catalog = get_catalog(api_key=api_key)

            free_catalog = {
                model.model_id
                for model in free_models(catalog)
            }

            if requested:
                # Catalog IDs are provider/model IDs. Normalize to the
                # explicit OpenRouter LiteLLM provider namespace.
                catalog_id = requested.removeprefix("openrouter/")

                if catalog_id not in free_catalog:
                    return None

                return _openrouter_model_ref(catalog_id)

            selected = select_free_coding_model(catalog)
            return _openrouter_model_ref(selected.model_id)

        except Exception:
            return None

    # Paid/custom mode is intentionally explicit for now.
    # We do not discover or choose paid models dynamically.
    if requested:
        return requested

    return None


def resolve_aider_providers(
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[AiderProvider, ...]:
    """Return deterministic development-provider order.

    OpenRouter is primary, Gemini secondary.

    OpenRouter is included only when:
      1. cloud development is explicitly enabled,
      2. an API credential exists, and
      3. the selected model passes the current free-tier policy.

    A failed OpenRouter catalog lookup never causes a paid model to be used.
    """

    env: dict[str, str] = dict(os.environ if environ is None else environ)
    providers: list[AiderProvider] = []

    if _cloud_enabled(env):
        if env.get("OPENROUTER_API_KEY", "").strip():
            openrouter_model = _select_openrouter_model(env)

            if openrouter_model:
                providers.append(
                    AiderProvider(
                        name="openrouter",
                        model=openrouter_model,
                        api_base="https://openrouter.ai/api/v1",
                        api_key_env="OPENROUTER_API_KEY",
                    )
                )

        if env.get("GEMINI_API_KEY", "").strip():
            providers.append(
                AiderProvider(
                    name="gemini",
                    model=env.get(
                        "AIDER_GEMINI_MODEL",
                        DEFAULT_GEMINI_MODEL,
                    ),
                    api_base="https://generativelanguage.googleapis.com",
                    api_key_env="GEMINI_API_KEY",
                )
            )

    return tuple(providers)
