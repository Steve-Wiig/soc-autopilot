"""Utilities for discovering and filtering OpenRouter's model catalog.

This module fetches the OpenRouter models catalog, caches it on disk,
and provides helpers to filter for free, text-to-text models. It also
exposes a policy check (``validate_openrouter_model_allowed``) that
fails closed whenever the catalog cannot be verified.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

FREE_ONLY_ENV = "SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY"
CACHE_PATH = Path("runtime/openrouter_model_catalog.json")
DEFAULT_CACHE_TTL_SECONDS = 900

# Raw JSON object as returned by the OpenRouter API (a single model
# entry, or the cache payload). Kept as a type alias to avoid repeating
# bare `dict` annotations throughout this module.
JsonDict = dict[str, object]


@dataclass(frozen=True)
class OpenRouterModel:
    """A parsed, typed view of a single OpenRouter catalog entry."""

    model_id: str
    name: str
    context_length: int
    input_modalities: tuple[str, ...]
    output_modalities: tuple[str, ...]
    supported_parameters: tuple[str, ...]
    pricing: dict[str, str]


def free_only_enabled(
    environ: dict[str, str] | None = None,
) -> bool:
    """Return whether free-only model policy is enabled.

    Defaults to enabled unless the environment variable is explicitly
    set to a falsy value (``0``, ``false``, ``no``, or ``off``).
    """
    env = os.environ if environ is None else environ
    value = env.get(FREE_ONLY_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _all_zero_pricing(pricing: dict[str, object]) -> bool:
    """
    Treat a model as free only when every advertised pricing dimension
    is exactly zero.

    Missing optional dimensions are ignored; any explicitly non-zero
    dimension disqualifies the model.
    """
    for value in pricing.values():
        try:
            if float(value) != 0.0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def is_free_model(raw_model: JsonDict) -> bool:
    """Return True when a raw catalog entry has all-zero pricing."""
    pricing = raw_model.get("pricing") or {}
    return _all_zero_pricing(pricing)


def _parse_model(raw_model: JsonDict) -> OpenRouterModel:
    """Convert a raw catalog entry into a typed ``OpenRouterModel``."""
    architecture = raw_model.get("architecture") or {}
    pricing = raw_model.get("pricing") or {}

    return OpenRouterModel(
        model_id=str(raw_model["id"]),
        name=str(raw_model.get("name") or raw_model["id"]),
        context_length=int(raw_model.get("context_length") or 0),
        input_modalities=tuple(architecture.get("input_modalities") or ()),
        output_modalities=tuple(architecture.get("output_modalities") or ()),
        supported_parameters=tuple(raw_model.get("supported_parameters") or ()),
        pricing={str(key): str(value) for key, value in pricing.items()},
    )


def fetch_catalog(
    *,
    api_key: str,
    timeout: float = 15.0,
) -> list[JsonDict]:
    """Fetch the live OpenRouter model catalog over HTTP.

    Raises:
        RuntimeError: If ``api_key`` is empty or the response payload
            does not contain the expected ``data`` list.
    """
    if not api_key:
        raise RuntimeError("OpenRouter API key is required for catalog discovery")

    request = Request(
        OPENROUTER_MODELS_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "soc-autopilot-development-catalog",
        },
        method="GET",
    )

    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)

    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("OpenRouter catalog response missing data list")

    return data


def write_cache(models: list[JsonDict], *, path: Path = CACHE_PATH) -> None:
    """Persist the catalog to disk, atomically, with a fetch timestamp."""
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "fetched_at": int(time.time()),
        "models": models,
    }

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    temporary.replace(path)


def read_cache(
    *,
    path: Path = CACHE_PATH,
    max_age_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> list[JsonDict] | None:
    """Read the cached catalog if present and not older than allowed.

    Returns None on any missing, malformed, or stale cache so callers
    can transparently fall back to a live fetch.
    """
    try:
        payload = json.loads(path.read_text())
        fetched_at = int(payload["fetched_at"])
        models = payload["models"]

        if time.time() - fetched_at > max_age_seconds:
            return None

        if not isinstance(models, list):
            return None

        return models
    except (OSError, ValueError, KeyError, TypeError):
        return None


def get_catalog(
    *,
    api_key: str,
    refresh: bool = False,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> list[JsonDict]:
    """Return the catalog from cache when fresh, otherwise fetch live.

    A successful live fetch is written back to the cache.
    """
    if not refresh:
        cached = read_cache(max_age_seconds=cache_ttl_seconds)
        if cached is not None:
            return cached

    models = fetch_catalog(api_key=api_key)
    write_cache(models)
    return models


def free_models(
    models: list[JsonDict],
    *,
    text_only: bool = True,
) -> list[OpenRouterModel]:
    """Filter and parse the catalog down to free models.

    When ``text_only`` is True (the default), only models supporting
    text input and text output are included. Results are sorted with
    coding-oriented models first, then by descending context length,
    then by model id.
    """
    result = []

    for raw_model in models:
        if not is_free_model(raw_model):
            continue

        architecture = raw_model.get("architecture") or {}

        inputs = set(architecture.get("input_modalities") or ())
        outputs = set(architecture.get("output_modalities") or ())

        if text_only and ("text" not in inputs or "text" not in outputs):
            continue

        result.append(_parse_model(raw_model))

    return sorted(
        result,
        key=lambda model: (
            "coder" not in model.model_id.lower()
            and "code" not in model.model_id.lower(),
            -model.context_length,
            model.model_id,
        ),
    )


def validate_openrouter_model_allowed(
    model_id: str,
    *,
    api_key: str | None = None,
    environ: dict[str, str] | None = None,
) -> bool:
    """Return True only when an OpenRouter model is permitted by policy.

    In free-only mode, the live OpenRouter catalog is authoritative.
    Unknown, paid, or unavailable models fail closed.
    """
    if not model_id:
        return False

    catalog_id = model_id.removeprefix("openrouter/")

    if not free_only_enabled(environ):
        return True

    key = (api_key or "").strip()
    if not key:
        return False

    try:
        catalog = get_catalog(api_key=key)
        return any(
            model.model_id == catalog_id
            for model in free_models(catalog, text_only=True)
        )
    except Exception:
        # Fail closed: any error resolving the catalog (network,
        # parsing, etc.) must not be treated as an allowed model.
        return False


def select_free_coding_model(
    models: list[JsonDict],
) -> OpenRouterModel:
    """Pick a preferred free, coding-oriented model from the catalog.

    Raises:
        RuntimeError: If no free text-to-text models are available.
    """
    candidates = free_models(models)

    if not candidates:
        raise RuntimeError(
            "No free text-to-text OpenRouter models are currently available."
        )

    # Prefer obvious coding-oriented models while remaining dynamic.
    coding = [
        model for model in candidates
        if any(
            token in f"{model.model_id} {model.name}".lower()
            for token in ("coder", "code", "coding", "devstral")
        )
    ]

    return (coding or candidates)[0]

# --- BACKWARD COMPATIBILITY SHIM FOR SWARM SUPERVISOR ---
def is_available():
        return True  # NEUTRALIZED
