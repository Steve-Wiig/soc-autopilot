import argparse
import os
import requests
import json
import sys
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union
from engine.sanitization_pipeline import sanitize_payload
from engine.writeback.authorization import (
    WritebackAuthorization,
    parse_writeback_authorization,
)

"""
TheHive Case Writeback Adapter

This module provides functionality to create cases in TheHive platform
from structured case data. It handles payload sanitization, API communication,
and audit logging for SOC automation workflows.

Usage:
    python -m thehive_writeback.handoff --case-data '{"title": "...", "description": "..."}' \
        --api-key <key> --url <url> [--mode draft|live] [--log-path <path>]

Environment Variables:
    HANDOFF_LOG_PATH: Default path for handoff log file (default: handoff_log.txt)
"""

REQUIRED_CASE_FIELDS = {'title', 'description'}

SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|apikey)\s*[:=]\s*[\w\-]{20,}'),
    re.compile(r'(?i)(password|passwd|pwd)\s*[:=]\s*\S+'),
    re.compile(r'(?i)(token|access[_-]?token|bearer)\s*[:=]\s*[\w\-]{20,}'),
    re.compile(r'(?i)(secret|client[_-]?secret)\s*[:=]\s*[\w\-]{20,}'),
    re.compile(r'(?i)(authorization|auth)\s*[:=]\s*Bearer\s+\S+'),
    re.compile(r'[\w\-]{32,}'),
    re.compile(r'sk-[\w\-]{20,}'),
    re.compile(r'gh[pousr]_[A-Za-z0-9]{36,}'),
    re.compile(r'xox[baprs]-[\w\-]{10,}'),
]

_LOGGER_CACHE: dict[str, logging.Logger] = {}
_SESSION: Optional[requests.Session] = None


class TheHiveWritebackAdapter:
    """Class-based adapter for TheHive case writeback with isolated session and logger state."""

    def __init__(self, session: Optional[requests.Session] = None, logger_cache: Optional[dict[str, logging.Logger]] = None):
        self._session = session
        self._logger_cache = logger_cache if logger_cache is not None else {}

    def _get_session(self) -> requests.Session:
        """Get or create a requests Session for connection pooling."""
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _setup_logger(self, log_path: Path) -> logging.Logger:
        """Configure a file logger for handoff audit trail.

        Args:
            log_path: Path to the log file.

        Returns:
            Configured logger instance with file handler.
        """
        cache_key = str(log_path.resolve())
        if cache_key in self._logger_cache:
            return self._logger_cache[cache_key]

        logger_name = f"thehive_writeback.handoff.{log_path}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()
        handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        self._logger_cache[cache_key] = logger
        return logger

    def verify_sanitization(self, payload: Any, context: str = "payload") -> None:
        """Verify that payload contains no secrets or high-entropy tokens.

        Args:
            payload: The sanitized payload to verify.
            context: Description of the payload for error messages.

        Raises:
            ValueError: If any secret pattern is detected in the payload.
        """
        payload_str = json.dumps(payload, ensure_ascii=False)
        for pattern in SECRET_PATTERNS:
            match = pattern.search(payload_str)
            if match:
                raise ValueError(
                    f"Sanitization verification failed: potential secret detected in {context} "
                    f"(pattern: {pattern.pattern}, match: {match.group()[:50]})"
                )

    def build_payload(self, raw_data: Any, mode: str) -> Any:
        """Build and sanitize the case payload for TheHive API.

        This function creates a copy of the input data to avoid mutating
        the caller's original dictionary.

        Args:
            raw_data: Raw case data dictionary.
            mode: Operation mode ('draft' or 'live').

        Returns:
            Sanitized payload ready for TheHive API submission.

        Raises:
            ValueError: If sanitization fails due to invalid data or secrets remain.
        """
        data = dict(raw_data)
        if mode == 'draft':
            data['status'] = 'Open'
            data['tags'] = data.get('tags', []) + ['draft-mode']
        sanitized = sanitize_payload(data)
        self.verify_sanitization(sanitized, "sanitized payload")
        return sanitized

    def call_thehive_api(self, url: str, api_key: str, payload: Any, authorization: WritebackAuthorization | None = None) -> str:
        """Create a case in TheHive via REST API.

        Args:
            url: TheHive base URL (e.g., 'https://thehive.example.com').
            api_key: TheHive API key for authentication.
            payload: Sanitized case payload dictionary.

        Returns:
            TheHive case ID string.

        Raises:
            RuntimeError: If API returns error status or missing case ID in response.
            requests.exceptions.RequestException: If network request fails.
        """
        if authorization is None:
            raise RuntimeError(
                "Live TheHive writeback requires explicit WritebackAuthorization"
            )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        session = self._get_session()
        response = session.post(
            f"{url}/api/case",
            json=payload,
            headers=headers,
            timeout=30
        )
        if response.status_code not in [200, 201]:
            raise RuntimeError(f"TheHive API error: {response.status_code} - {response.text}")
        case_id = response.json().get('id')
        if not case_id:
            raise RuntimeError("TheHive API response missing case ID")
        return case_id

    def log_handoff(self, log_path: Path, case_id: str, mode: str) -> None:
        """Log successful case creation to handoff audit file.

        Args:
            log_path: Path to the handoff log file.
            case_id: TheHive case ID that was created.
            mode: Operation mode ('draft' or 'live').

        Returns:
            None
        """
        logger = self._setup_logger(log_path)
        now = datetime.now(timezone.utc)
        logger.info(f"{now.isoformat()}|REF:{case_id}|STATUS:SUCCESS|MODE:{mode}")

    def main(self, args: argparse.Namespace) -> Union[str, int]:
        """Main entry point for TheHive case writeback adapter.

        Parses arguments, validates input, creates case in TheHive,
        and logs the handoff result.

        Args:
            args: Parsed command-line arguments.

        Returns:
            Case ID string on success, or integer exit code on failure:
            - 1: Missing required fields or TheHive API error
            - 2: Invalid JSON in case-data
            - 3: Network/request exception
            - 4: Sanitization verification failed
        """
        log_path = Path(args.log_path) if args.log_path else Path(os.environ.get("HANDOFF_LOG_PATH", "handoff_log.txt"))
        try:
            raw_data: Any = json.loads(args.case_data)
        except json.JSONDecodeError:
            return 2
        missing = REQUIRED_CASE_FIELDS - set(raw_data.keys())
        if missing:
            print(f"Missing required fields: {missing}", file=sys.stderr)
            return 1
        try:
            sanitized_data = self.build_payload(raw_data, args.mode)
        except ValueError as e:
            print(f"Sanitization error: {e}", file=sys.stderr)
            return 4
        try:
            authorization = None
            if args.mode == "live":
                if not args.authorization_token:
                    raise RuntimeError(
                        "--authorization-token is required for live TheHive writeback"
                    )
                authorization = parse_writeback_authorization(
                    args.authorization_token,
                    expected_target="thehive",
                )

            case_id = self.call_thehive_api(
                args.url,
                args.api_key,
                sanitized_data,
                authorization=authorization,
            )
            self.log_handoff(log_path, case_id, args.mode)
            return case_id
        except requests.exceptions.RequestException as e:
            error_logger = logging.getLogger("thehive_writeback.handoff.error")
            error_logger.setLevel(logging.ERROR)
            if not error_logger.handlers:
                handler = logging.StreamHandler(sys.stderr)
                handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
                error_logger.addHandler(handler)
            error_logger.exception("TheHive API request failed for URL %s with payload %s", args.url, sanitized_data)
            return 3
        except RuntimeError:
            return 1


_default_adapter = TheHiveWritebackAdapter(session=_SESSION, logger_cache=_LOGGER_CACHE)


def create_adapter() -> TheHiveWritebackAdapter:
    """Factory function to create a new isolated TheHiveWritebackAdapter instance.

    Returns:
        A new TheHiveWritebackAdapter with fresh session and logger cache.
    """
    return TheHiveWritebackAdapter()


def _get_session() -> requests.Session:
    """Get or create a requests Session for connection pooling (module-level backward compatibility)."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


def _setup_logger(log_path: Path) -> logging.Logger:
    """Configure a file logger for handoff audit trail (module-level backward compatibility).

    Args:
        log_path: Path to the log file.

    Returns:
        Configured logger instance with file handler.
    """
    cache_key = str(log_path.resolve())
    if cache_key in _LOGGER_CACHE:
        return _LOGGER_CACHE[cache_key]

    logger_name = f"thehive_writeback.handoff.{log_path}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    _LOGGER_CACHE[cache_key] = logger
    return logger


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the TheHive writeback adapter.

    Returns:
        Parsed arguments namespace with attributes:
        - case_data: JSON string of case data
        - api_key: TheHive API key
        - url: TheHive base URL
        - mode: Operation mode ('draft' or 'live')
        - log_path: Optional path to handoff log file
    """
    parser = argparse.ArgumentParser(description=f"TheHive Case Writeback Adapter v{__version__}")
    parser.add_argument("--case-data", required=True, help="JSON string of case data")
    parser.add_argument("--api-key", required=True, help="TheHive API Key")
    parser.add_argument("--url", required=True, help="TheHive Base URL")
    parser.add_argument("--mode", choices=['draft', 'live'], default='draft', help="Adapter mode")
    parser.add_argument(
        "--authorization-token",
        help="Signed authorization token required for live mode",
    )
    parser.add_argument("--log-path", help="Path to the handoff log file (overrides HANDOFF_LOG_PATH env var and default)")
    return parser.parse_args()

def verify_sanitization(payload: Any, context: str = "payload") -> None:
    """Verify that payload contains no secrets or high-entropy tokens (module-level backward compatibility).

    Args:
        payload: The sanitized payload to verify.
        context: Description of the payload for error messages.

    Raises:
        ValueError: If any secret pattern is detected in the payload.
    """
    payload_str = json.dumps(payload, ensure_ascii=False)
    for pattern in SECRET_PATTERNS:
        if pattern.search(payload_str):
            raise ValueError(f"Secret pattern detected in {context}")

def build_payload(raw_data: Any, mode: str) -> Any:
    """Build and sanitize the case payload for TheHive API (module-level backward compatibility).

    This function creates a copy of the input data to avoid mutating
    the caller's original dictionary.

    Args:
        raw_data: Raw case data dictionary.
        mode: Operation mode ('draft' or 'live').

    Returns:
        Sanitized payload ready for TheHive API submission.

    Raises:
        ValueError: If sanitization fails due to invalid data or secrets remain.
    """
    return _default_adapter.build_payload(raw_data, mode)


def call_thehive_api(url: str, api_key: str, payload: Any, authorization: WritebackAuthorization | None = None) -> str:
    """Create a case in TheHive via REST API (module-level backward compatibility).


    Args:
        url: TheHive base URL.
        api_key: TheHive API key.
        payload: Sanitized case payload.

    Returns:
        TheHive case ID.

    Raises:
        RuntimeError: If API call fails.
    """
    return _default_adapter.call_thehive_api(url, api_key, payload, authorization=authorization)


def log_handoff(log_path: Path, case_id: str, mode: str) -> None:
    """Log successful case creation to handoff audit file (module-level backward compatibility).

    Args:
        log_path: Path to the handoff log file.
        case_id: TheHive case ID that was created.
        mode: Operation mode ('draft' or 'live').

    Returns:
        None
    """
    _default_adapter.log_handoff(log_path, case_id, mode)


def main() -> Union[str, int]:
    """Module-level main entry point for CLI execution.

    Returns:
        Case ID string on success, or integer exit code on failure.
    """
    args = parse_args()
    if getattr(args, 'test_sanitization', False):
        print("Error: --test-sanitization is no longer supported. Use pytest for test discovery.", file=sys.stderr)
        return 1
    return _default_adapter.main(args)

__version__ = "1.0.0"

if __name__ == "__main__":
    result = main()
    if isinstance(result, int):
        sys.exit(result)
    else:
        print(result)
