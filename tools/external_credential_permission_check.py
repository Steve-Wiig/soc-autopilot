import os
import sys
import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests import Session
from pydantic import BaseModel, field_validator, Field

DEFAULT_CONFIG_PATH: str = str(Path(__file__).parent / "config.json")

REQUIRED_KEYS = {"user_env", "token_env", "read", "forbidden", "forbidden_method"}
VALID_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
SUCCESS_CODES = {200, 201}
DENIED_CODES = {401, 403}

MOCK_USER = "mock_user"
MOCK_TOKEN = "mock_token"

MAX_CONCURRENT_CHECKS = 10


def sanitize_token(token: Optional[str]) -> str:
    if not token:
        return "****"
    if len(token) <= 4:
        return "****"
    return token[:4] + "****"


def sanitize_auth(auth: Optional[Tuple[str, str]]) -> Tuple[str, str]:
    if not auth:
        return ("****", "****")
    user, token = auth
    return (user, sanitize_token(token))


class Config(BaseModel):
    user_env: str = Field(..., description="Environment variable name for the API user")
    token_env: str = Field(..., description="Environment variable name for the API token")
    read: str = Field(..., description="Path for the read endpoint (must start with '/')")
    forbidden: str = Field(..., description="Path for the forbidden endpoint (must start with '/')")
    forbidden_method: str = Field(..., description="HTTP method to test (must be in VALID_METHODS)")

    @field_validator("forbidden_method")
    @classmethod
    def validate_forbidden_method(cls, v: str) -> str:
        v = v.upper()
        if v not in VALID_METHODS:
            raise ValueError(f"Invalid forbidden_method: {v}. Must be one of {VALID_METHODS}")
        return v

    @field_validator("read", "forbidden")
    @classmethod
    def validate_paths(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"Path must start with '/': {v}")
        return v


def validate_config(config: Dict[str, Config]) -> None:
    """
    Validate the configuration dictionary for all services.

    Validates that each service config contains all REQUIRED_KEYS:
        - user_env: environment variable name for the API user
        - token_env: environment variable name for the API token
        - read: path for the read endpoint (must start with '/')
        - forbidden: path for the forbidden endpoint (must start with '/')
        - forbidden_method: HTTP method to test (must be in VALID_METHODS)

    VALID_METHODS: {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}

    Side effects:
        - Mutates `config` in-place: normalizes `forbidden_method` to uppercase.

    Raises:
        ValueError: If config is not a dict, a service config is not a dict,
                    required keys are missing, forbidden_method is invalid,
                    or read/forbidden paths don't start with '/'.
    """
    if not isinstance(config, dict):
        raise ValueError("Config must be a dictionary mapping service names to config objects")

    for service, cfg in config.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"Service '{service}' config must be a dictionary")

        missing = REQUIRED_KEYS - set(cfg.keys())
        if missing:
            raise ValueError(f"Service '{service}' missing required keys: {missing}")


def load_config(config_path: Optional[str] = None) -> Dict[str, Config]:
    """
    Load and validate the configuration file.

    Args:
        config_path: Path to the configuration file. If None, uses the default path.

    Returns:
        A dictionary mapping service names to Config objects.

    Raises:
        RuntimeError: If the config file is not found or is invalid.
    """
    path = config_path or os.getenv("CONFIG_FILE", DEFAULT_CONFIG_PATH)
    try:
        with open(path, "r") as f:
            config = json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"CONFIG ERROR: config file not found at {path}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CONFIG ERROR: invalid JSON in {path}: {exc}")

    try:
        validate_config(config)
    except ValueError as exc:
        raise RuntimeError(f"CONFIG ERROR: validation failed: {exc}")

    return {service: Config(**cfg) for service, cfg in config.items()}


@dataclass
class MockResponse:
    status_code: int


def get_mock_response(status_code: int) -> MockResponse:
    """
    Create a mock response object.

    Args:
        status_code: HTTP status code for the mock response.

    Returns:
        A MockResponse object.
    """
    return MockResponse(status_code)


def check_service(service: str, cfg: Config, lab_url: str, session: Optional[Session], dry_run: bool = False) -> bool:
    """
    Verify credential permissions for a single service.

    Args:
        service: Name of the service being checked (used for logging).
        cfg: Service configuration dict with keys 'user_env', 'token_env', 'read',
             'forbidden', and 'forbidden_method'.
        lab_url: Base URL of the lab environment (trailing slash optional).
        session: requests.Session for making HTTP requests, or None in dry-run mode.
        dry_run: If True, use mock credentials and mock responses instead of real requests.

    Returns:
        True if read access succeeds and forbidden action is properly denied; False otherwise.

    Side Effects:
        Logs errors on failure, logs info on success. Makes HTTP requests when not in dry-run mode.
    """
    import requests

    user = os.getenv(cfg.user_env, MOCK_USER) if dry_run else os.getenv(cfg.user_env)
    token = os.getenv(cfg.token_env, MOCK_TOKEN) if dry_run else os.getenv(cfg.token_env)

    if not user or not token:
        logging.error("CONFIG ERROR: missing credentials for %s (user=%s, token=%s)", service, user, sanitize_token(token))
        return False

    auth = (user, token)
    read_url = lab_url.rstrip("/") + cfg.read
    forbidden_url = lab_url.rstrip("/") + cfg.forbidden

    try:
        if dry_run:
            read_resp = get_mock_response(200)
            forbidden_resp = get_mock_response(403)
        else:
            read_resp = session.get(read_url, auth=auth, timeout=10, verify=False)
            forbidden_resp = session.request(cfg.forbidden_method, forbidden_url, auth=auth, timeout=10, verify=False)

        if read_resp.status_code not in SUCCESS_CODES:
            logging.error("FAIL: %s read access denied: %s (auth=%s)", service, read_resp.status_code, sanitize_auth(auth))
            return False

        if forbidden_resp.status_code not in DENIED_CODES:
            logging.error("FAIL: %s forbidden action was not denied: %s (auth=%s)", service, forbidden_resp.status_code, sanitize_auth(auth))
            return False

    except Exception as exc:
        logging.error("FAIL: %s request failed: %s (auth=%s)", service, exc, sanitize_auth(auth))
        return False

    logging.info("PASS: %s credential permissions verified", service)
    return True


def main() -> int:
    """
    Main function to verify credential permissions for services.

    Returns:
        0 if all services pass, 1 if any service fails.
    """
    import requests
    from requests.adapters import HTTPAdapter

    def create_session(max_workers: int) -> Session:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def process_results(results: List[Tuple[str, bool]]) -> int:
        success = all(r[1] for r in results)
        for service, ok in results:
            status = "PASS" if ok else "FAIL"
            print(f"{status}: {service}")
        return 0 if success else 1

    parser = argparse.ArgumentParser(description="Verify credential permissions for services.")
    parser.add_argument("--config", "-c", help="Path to config JSON file", default=None)
    parser.add_argument("--lab-url", "-l", required=True, help="Base URL of lab environment")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Use mock responses")
    args = parser.parse_args()

    config = load_config(args.config)

    max_workers = min(len(config), MAX_CONCURRENT_CHECKS)
    session = None
    if not args.dry_run:
        session = create_session(max_workers)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_service, service, cfg, args.lab_url, session, args.dry_run): service for service, cfg in config.items()}
        for future in as_completed(futures):
            service = futures[future]
            try:
                result = future.result()
                results.append((service, result))
            except Exception as exc:
                logging.error("FAIL: %s raised exception: %s", service, exc)
                results.append((service, False))

    return process_results(results)


if __name__ == "__main__":
    sys.exit(main())
