
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


@dataclass(frozen=True)
class OpenRouterModel:
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


def is_free_model(model: dict) -> bool:
    pricing = model.get("pricing") or {}
    return _all_zero_pricing(pricing)


def _parse_model(raw: dict) -> OpenRouterModel:
    architecture = raw.get("architecture") or {}
    pricing = raw.get("pricing") or {}

    return OpenRouterModel(
        model_id=str(raw["id"]),
        name=str(raw.get("name") or raw["id"]),
        context_length=int(raw.get("context_length") or 0),
        input_modalities=tuple(architecture.get("input_modalities") or ()),
        output_modalities=tuple(architecture.get("output_modalities") or ()),
        supported_parameters=tuple(raw.get("supported_parameters") or ()),
        pricing={str(k): str(v) for k, v in pricing.items()},
    )


def fetch_catalog(
    *,
    api_key: str,
    timeout: float = 15.0,
) -> list[dict]:
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


def write_cache(models: list[dict], *, path: Path = CACHE_PATH) -> None:
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
) -> list[dict] | None:
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
) -> list[dict]:
    if not refresh:
        cached = read_cache(max_age_seconds=cache_ttl_seconds)
        if cached is not None:
            return cached

    models = fetch_catalog(api_key=api_key)
    write_cache(models)
    return models


def free_models(
    models: list[dict],
    *,
    text_only: bool = True,
) -> list[OpenRouterModel]:
    result = []

    for raw in models:
        if not is_free_model(raw):
            continue

        architecture = raw.get("architecture") or {}

        inputs = set(architecture.get("input_modalities") or ())
        outputs = set(architecture.get("output_modalities") or ())

        if text_only and ("text" not in inputs or "text" not in outputs):
            continue

        result.append(_parse_model(raw))

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
        return False


def select_free_coding_model(
    models: list[dict],
) -> OpenRouterModel:
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
