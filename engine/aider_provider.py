"""Development-only Aider provider selection.

This module is intentionally separate from the SOC ModelRouter.

Trust boundary:
    - Production SOC inference remains LOCAL_SOC only.
    - These providers are for bounded development-worker execution.
    - Cloud development requires explicit opt-in.
    - OpenRouter development is free-tier-only by default.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Sequence, Optional
import os
import logging

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


class ProviderCatalogABC(ABC):
    """
    Abstract interface for provider catalogs.

    Decouples provider selection logic from external API implementations.
    Implementations must be deterministic and side-effect-free for a given
    environment snapshot.
    """

    priority: int = 100

    @abstractmethod
    def list_available(self, env: Mapping[str, str]) -> Sequence[AiderProvider]:
        """
        Return all available providers for the given environment.

        Args:
            env: Environment variable mapping.

        Returns:
            Sequence of available AiderProvider instances, ordered by preference.
        """
        ...

    @abstractmethod
    def select_primary(self, env: Mapping[str, str]) -> AiderProvider | None:
        """
        Return the single best provider for the given environment.

        Args:
            env: Environment variable mapping.

        Returns:
            The primary AiderProvider, or None if no providers are available.
        """
        ...


class OpenRouterCatalog(ProviderCatalogABC):
    """
    OpenRouter provider catalog implementation.

    Encapsulates free-tier policy enforcement and catalog lookup logic.
    """

    priority: int = 10

    def __init__(self, catalog_data: Optional[dict] = None):
        self.catalog_data = catalog_data

    def list_available(self, env: Mapping[str, str]) -> Sequence[AiderProvider]:
        providers: list[AiderProvider] = []

        if not _cloud_enabled(env):
            return providers

        api_key = env.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            return providers

        if free_only_enabled(env) and self.catalog_data is None:
            try:
                catalog = get_catalog(api_key=api_key)
                if not catalog:
                    logging.warning("OpenRouter free-only mode requires catalog data but none provided; skipping.")
                    return providers
            except Exception:
                logging.warning("OpenRouter free-only mode requires catalog data but none provided; skipping.")
                return providers

        model = _select_openrouter_model(env)
        if model:
            providers.append(
                AiderProvider(
                    name="openrouter",
                    model=model,
                    api_base="https://openrouter.ai/api/v1",
                    api_key_env="OPENROUTER_API_KEY",
                )
            )

        return providers

    def select_primary(self, env: Mapping[str, str]) -> AiderProvider | None:
        available = self.list_available(env)
        return available[0] if available else None


class GeminiCatalog(ProviderCatalogABC):
    """
    Gemini provider catalog implementation.
    """

    priority: int = 20

    def list_available(self, env: Mapping[str, str]) -> Sequence[AiderProvider]:
        providers: list[AiderProvider] = []

        if not _cloud_enabled(env):
            return providers

        api_key = env.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            return providers

        providers.append(
            AiderProvider(
                name="gemini",
                model=env.get("AIDER_GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
                api_base="https://generativelanguage.googleapis.com",
                api_key_env="GEMINI_API_KEY",
            )
        )

        return providers

    def select_primary(self, env: Mapping[str, str]) -> AiderProvider | None:
        available = self.list_available(env)
        return available[0] if available else None


class CompositeCatalog(ProviderCatalogABC):
    """
    Composite catalog that aggregates multiple provider catalogs.

    Maintains a fixed priority order: OpenRouter first, then Gemini.
    """

    def __init__(self, catalogs: Sequence[ProviderCatalogABC]) -> None:
        self._catalogs = sorted(list(catalogs), key=lambda c: c.priority)

    def list_available(self, env: Mapping[str, str]) -> Sequence[AiderProvider]:
        all_providers: list[AiderProvider] = []
        for catalog in self._catalogs:
            all_providers.extend(catalog.list_available(env))
        return all_providers

    def select_primary(self, env: Mapping[str, str]) -> AiderProvider | None:
        for catalog in self._catalogs:
            primary = catalog.select_primary(env)
            if primary:
                return primary
        return None


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


def _select_openrouter_model(env: Mapping[str, str], catalog_data: Optional[dict] = None) -> str | None:
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
        if catalog_data is None:
            return None
        try:
            catalog = catalog_data

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

        except (ValueError, KeyError, TypeError) as e:
            logging.error(f"OpenRouter catalog data parsing error: {e}")
            return None

    # Paid/custom mode is intentionally explicit for now.
    # We do not discover or choose paid models dynamically.
    if requested:
        return requested

    return None


def resolve_aider_providers(
    *,
    environ: Mapping[str, str] | None = None,
    catalog: ProviderCatalogABC | None = None,
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

    if catalog is None:
        catalog = CompositeCatalog([
            OpenRouterCatalog(),
            GeminiCatalog(),
        ])

    return tuple(catalog.list_available(env))
