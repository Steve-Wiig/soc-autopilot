import argparse
import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Callable

import requests
from engine.writeback.authorization import (
    WritebackAuthorization,
    parse_writeback_authorization,
)

# Module-level session for HTTP connection pooling (TCP keepalive)
_HTTP_SESSION = requests.Session()


DRAFT_CASE_ID = 'DRAFT_ID_000'
DEFAULT_LEDGER_PATH = 'handoffs_ledger.log'
DEFAULT_TIMEOUT = 10
ENV_TIMEOUT = 'SO_API_TIMEOUT'
ENV_LEDGER_PATH = 'SO_LEDGER_PATH'
ENV_HMAC_KEY = 'SO_LEDGER_HMAC_KEY'
ENV_HMAC_KEY_ID = 'SO_LEDGER_HMAC_KEY_ID'

# Resolved at runtime via _load_config()
_LEDGER_PATH: str = DEFAULT_LEDGER_PATH
_HMAC_KEY: bytes = b''
_HMAC_KEY_ID: str = 'default'

# Regex patterns for secret redaction
_SECRET_PATTERNS = [
    (re.compile(r'(?i)(api[_-]?key|apikey|access[_-]?token|secret[_-]?key|auth[_-]?token)\s*[:=]\s*[\w\-]{20,}'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)(password|passwd|pwd)\s*[:=]\s*\S+'), r'\1=***REDACTED***'),
    (re.compile(r'eyJ[\w\-]+\.eyJ[\w\-]+\.[\w\-]+'), '***JWT_REDACTED***'),
    (re.compile(r'(?i)bearer\s+[\w\-]{20,}'), 'Bearer ***REDACTED***'),
    (re.compile(r'(?i)authorization\s*[:=]\s*\S+'), 'Authorization=***REDACTED***'),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '***IP_REDACTED***'),
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '***EMAIL_REDACTED***'),
    (re.compile(r'(?i)(ssh[_-]?key|private[_-]?key)\s*[:=]\s*\S+'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*\S+'), 'aws_secret_access_key=***REDACTED***'),
    (re.compile(r'(?i)github[_-]?token\s*[:=]\s*\S+'), 'github_token=***REDACTED***'),
]


def _load_config() -> None:
    """Load configuration from environment variables."""
    global _LEDGER_PATH, _HMAC_KEY, _HMAC_KEY_ID
    env_path = os.environ.get(ENV_LEDGER_PATH)
    if env_path:
        _LEDGER_PATH = os.path.abspath(env_path)
    else:
        # Use XDG_DATA_HOME or fallback to /var/log
        xdg_data_home = os.environ.get('XDG_DATA_HOME')
        if xdg_data_home:
            base_dir = os.path.join(xdg_data_home, 'so-case-writeback')
        else:
            base_dir = '/var/log/so-case-writeback'
        os.makedirs(base_dir, exist_ok=True)
        _LEDGER_PATH = os.path.join(base_dir, DEFAULT_LEDGER_PATH)

    hmac_key = os.environ.get(ENV_HMAC_KEY)
    if hmac_key:
        _HMAC_KEY = hmac_key.encode('utf-8')
    hmac_key_id = os.environ.get(ENV_HMAC_KEY_ID)
    if hmac_key_id:
        _HMAC_KEY_ID = hmac_key_id


def configure_logging() -> None:
    """Configure logging for the application."""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def _redact_secrets(text: str) -> str:
    """Redact secrets, high-entropy tokens, and PII from text."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_input(data: Any) -> Dict[str, str]:
    """Sanitizes input dictionary by redacting secrets then truncating keys and values.

    Args:
        data: The input data to sanitize.

    Returns:
        A dictionary with keys truncated to 64 chars and values to 2048 chars,
        with secrets redacted.
    """
    if not isinstance(data, dict):
        return {}
    sanitized = {}
    for k, v in data.items():
        key_str = str(k)[:64]
        val_str = str(v)[:2048]
        val_str = _redact_secrets(val_str)
        sanitized[key_str] = val_str
    return sanitized


def create_case_draft(sanitized: Dict[str, str]) -> str:
    """Creates a draft case by logging and returning a mock ID.

    Args:
        sanitized: The sanitized payload.

    Returns:
        A draft case identifier.
    """
    logging.info(f"DRAFT MODE: Payload sanitized: {sanitized}")
    return DRAFT_CASE_ID


def create_case_live(api_url: str, api_key: str, sanitized: Dict[str, str], timeout: int = DEFAULT_TIMEOUT) -> str:
    """Creates a case via the Security Onion API.

    Args:
        api_url: The base URL of the API.
        api_key: The authorization token.
        sanitized: The sanitized payload.
        timeout: Request timeout in seconds.

    Returns:
        The ID of the created case.

    Raises:
        RuntimeError: If the API request fails.
    """
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        response = _HTTP_SESSION.post(f"{api_url}/api/cases", json=sanitized, headers=headers, timeout=timeout)
        response.raise_for_status()
        case_id = response.json().get("id")
        return case_id
    except Exception as e:
        logging.error(f"API Failure: {e}")
        raise RuntimeError(f"Library code called exit(1)")


def _get_case_creator(draft_mode: bool) -> Callable[..., str]:
    """Factory function to get the appropriate case creator.

    Args:
        draft_mode: If True, returns draft creator; otherwise live creator.

    Returns:
        A callable that creates a case.
    """
    if draft_mode:
        return lambda sanitized, timeout=None: create_case_draft(sanitized)
    return lambda api_url, api_key, sanitized, timeout=DEFAULT_TIMEOUT: create_case_live(api_url, api_key, sanitized, timeout)


def create_case(api_url: str, api_key: str, payload: Dict[str, Any], draft_mode: bool, timeout: int = DEFAULT_TIMEOUT, authorization: WritebackAuthorization | None = None) -> str:
    """Creates a case via the Security Onion API (backward compatible).

    Args:
        api_url: The base URL of the API.
        api_key: The authorization token.
        payload: The case data to submit.
        draft_mode: If True, skips API call and returns a mock ID.
        timeout: Request timeout in seconds.

    Returns:
        The ID of the created case or a draft identifier.

    Raises:
        RuntimeError: If the API request fails.
    """
    sanitized = sanitize_input(payload)
    creator = _get_case_creator(draft_mode)
    
    if draft_mode:
        return creator(sanitized)

    if authorization is None:
        raise RuntimeError(
            "Live SO case writeback requires explicit WritebackAuthorization"
        )
    return creator(api_url, api_key, sanitized, timeout)


def _compute_hmac(line: str) -> str:
    """Compute HMAC-SHA256 of a line using the configured key.

    Args:
        line: The line content to sign (without HMAC field).

    Returns:
        Hex-encoded HMAC digest.
    """
    if not _HMAC_KEY:
        return 'NO_HMAC_KEY'
    return hmac.new(_HMAC_KEY, line.encode('utf-8'), hashlib.sha256).hexdigest()


def write_to_ledger(payload_ref: str, case_id: str, draft_mode: bool = False) -> None:
    """Writes the case transaction to the local handoff ledger with HMAC integrity.

    Args:
        payload_ref: The reference identifier from the payload.
        case_id: The ID of the created case.
        draft_mode: Whether the case was created in draft mode.

    Raises:
        RuntimeError: If the ledger file cannot be written to.
    """
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        line_content = f"{timestamp} | {payload_ref} | {case_id} | draft={draft_mode} | key_id={_HMAC_KEY_ID}"
        hmac_digest = _compute_hmac(line_content)
        full_line = f"{line_content} | hmac={hmac_digest}\n"
        with open(_LEDGER_PATH, "a") as f:
            f.write(full_line)
    except IOError:
        raise RuntimeError(f"Library code called exit(2)")


def main() -> None:
    """Parses command line arguments and executes the case writeback process."""
    _load_config()
    configure_logging()
    
    parser = argparse.ArgumentParser(description="SO Case Writeback Adapter")
    parser.add_argument("--url", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--payload", required=True, help="JSON string of case data")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument(
        "--authorization-token",
        help="Signed authorization token required for live mode",
    )
    parser.add_argument("--timeout", type=int, default=int(os.environ.get(ENV_TIMEOUT, DEFAULT_TIMEOUT)), help=f"API timeout in seconds (default: {DEFAULT_TIMEOUT}, env: {ENV_TIMEOUT})")
    
    args = parser.parse_args()

    try:
        data = json.loads(args.payload)
    except json.JSONDecodeError:
        raise RuntimeError(f"Library code called exit(2)")

    authorization = None
    if not args.draft:
        if not args.authorization_token:
            raise RuntimeError(
                "--authorization-token is required for live SO case writeback"
            )
        authorization = parse_writeback_authorization(
            args.authorization_token,
            expected_target="so_cases",
        )

    case_id = create_case(
        args.url,
        args.key,
        data,
        args.draft,
        args.timeout,
        authorization=authorization,
    )
    
    write_to_ledger(data.get("ref", "N/A"), case_id, args.draft)
    
    logging.info(f"SUCCESS: {case_id}")
    return


if __name__ == "__main__":
    main()
