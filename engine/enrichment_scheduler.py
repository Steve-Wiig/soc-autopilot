import argparse
import hashlib
import json
import logging
import os
import signal
import sqlite3
import time
import re
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from functools import wraps, lru_cache
from typing import Tuple, Dict, List, Optional, Any, Callable, Union

try:
    import psycopg2
except ImportError:
    psycopg2 = None


logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Enumeration of possible job statuses."""
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProviderNotConfiguredError(RuntimeError):
    """Raised when an enrichment provider is not configured in the quota ledger."""
    pass


class EnrichmentProvider(ABC):
    """Abstract base class for enrichment providers.

    Implementations must provide a `process` method that takes an IOC value
    and returns a dictionary with enrichment results.
    """

    @abstractmethod
    def process(self, ioc: str) -> Dict[str, Any]:
        """Process an IOC and return enrichment data.

        Args:
            ioc: The indicator of compromise to enrich.

        Returns:
            A dictionary containing enrichment results.
        """
        pass


class MockEnrichmentProvider(EnrichmentProvider):
    """Default mock enrichment provider for testing and development."""

    def process(self, ioc: str) -> Dict[str, Any]:
        """Return mock enrichment data for the given IOC."""
        return {"status": "enriched", "data": f"mock_data_for_{ioc}"}


_HIGH_ENTROPY_PATTERN = re.compile(r'[A-Za-z0-9+/=]{32,}')
_DEFAULT_SENSITIVE_PATTERNS = [
    'secret', 'token', 'password', 'key', 'api_key', 'apikey',
    'access_token', 'refresh_token', 'client_secret', 'private_key',
    _HIGH_ENTROPY_PATTERN
]
_ENV_SENSITIVE_PATTERNS = 'SENSITIVE_PATTERNS'


def _load_sensitive_patterns_from_env() -> List[Union[str, re.Pattern]]:
    """Load sensitive patterns from environment variable.

    The environment variable should contain a JSON array of strings.
    Strings starting with 'regex:' are compiled as regex patterns.

    Returns:
        List of pattern strings and compiled regex patterns.
    """
    env_value = os.getenv(_ENV_SENSITIVE_PATTERNS)
    if not env_value:
        return []
    try:
        patterns = json.loads(env_value)
        result = []
        for pat in patterns:
            if isinstance(pat, str) and pat.startswith('regex:'):
                result.append(re.compile(pat[6:]))
            else:
                result.append(pat)
        return result
    except (json.JSONDecodeError, re.error) as e:
        logger.warning("Failed to parse SENSITIVE_PATTERNS env var: %s", e)
        return []


class Sanitizer:
    """Sanitizes dictionaries by redacting sensitive fields.

    Encapsulates pattern compilation and caching logic for better testability
    and maintainability.
    """

    def __init__(self, sensitive_patterns: Optional[List[Union[str, re.Pattern]]] = None) -> None:
        """Initialize the sanitizer with optional custom patterns.

        Args:
            sensitive_patterns: List of substring patterns or compiled regex objects
                to detect sensitive keys. If None, uses default organizational patterns
                plus any patterns loaded from the SENSITIVE_PATTERNS environment variable.
        """
        if sensitive_patterns is None:
            sensitive_patterns = _DEFAULT_SENSITIVE_PATTERNS.copy()
            sensitive_patterns.extend(_load_sensitive_patterns_from_env())
        self._raw_patterns = sensitive_patterns
        self._string_patterns: List[str] = []
        self._regex_patterns: List[re.Pattern] = []
        self._compiled_string_regex: Optional[re.Pattern] = None
        self._compiled_regex_patterns: Optional[re.Pattern] = None
        self._separate_patterns()

    def _separate_patterns(self) -> None:
        """Separate string patterns from compiled regex patterns."""
        self._string_patterns = [p for p in self._raw_patterns if isinstance(p, str)]
        self._regex_patterns = [p for p in self._raw_patterns if isinstance(p, re.Pattern)]

    @lru_cache(maxsize=1)
    def _compile_string_patterns(self, patterns_tuple: Tuple[str, ...]) -> Optional[re.Pattern]:
        """Compile string patterns into a single case-insensitive regex.

        Uses lru_cache to avoid recompilation when patterns haven't changed.

        Args:
            patterns_tuple: Tuple of string patterns for cache key.

        Returns:
            Compiled regex pattern or None if no patterns.
        """
        if not patterns_tuple:
            return None
        return re.compile('|'.join(map(re.escape, patterns_tuple)), re.IGNORECASE)

    @lru_cache(maxsize=1)
    def _compile_regex_patterns(self, patterns_tuple: Tuple[str, ...]) -> Optional[re.Pattern]:
        """Compile regex patterns into a single combined regex.

        Uses lru_cache to avoid recompilation when patterns haven't changed.

        Args:
            patterns_tuple: Tuple of regex pattern strings for cache key.

        Returns:
            Compiled regex pattern or None if no patterns.
        """
        if not patterns_tuple:
            return None
        return re.compile('|'.join(f'(?:{p})' for p in patterns_tuple))

    def compile_patterns(self) -> None:
        """Compile string patterns into a single regex for efficient matching."""
        self._compiled_string_regex = self._compile_string_patterns(tuple(self._string_patterns))
        regex_pattern_strings = tuple(p.pattern for p in self._regex_patterns)
        self._compiled_regex_patterns = self._compile_regex_patterns(regex_pattern_strings)

    def is_sensitive(self, key: str) -> bool:
        """Check if a key matches any sensitive pattern.

        Args:
            key: The dictionary key to check.

        Returns:
            True if the key is considered sensitive, False otherwise.
        """
        if self._compiled_string_regex is None:
            self.compile_patterns()
        key_lower = key.lower()
        if self._compiled_string_regex and self._compiled_string_regex.search(key_lower):
            return True
        if self._compiled_regex_patterns and self._compiled_regex_patterns.search(key):
            return True
        return False

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively sanitize a dictionary by redacting sensitive fields.

        Args:
            data: The dictionary to sanitize.

        Returns:
            A new dictionary with sensitive values redacted.
        """
        if self._compiled_string_regex is None:
            self.compile_patterns()

        def _sanitize(obj: Any) -> Any:
            if isinstance(obj, dict):
                result = {}
                for k, v in obj.items():
                    if self.is_sensitive(k):
                        result[k] = "***REDACTED***"
                    else:
                        result[k] = _sanitize(v)
                return result
            elif isinstance(obj, list):
                return [_sanitize(item) for item in obj]
            elif isinstance(obj, str):
                if self._compiled_regex_patterns and self._compiled_regex_patterns.search(obj):
                    return "***REDACTED***"
                return obj
            else:
                return obj

        return _sanitize(data)

def sanitize(data: Dict[str, Any], sensitive_patterns: Optional[List[Union[str, re.Pattern]]] = None) -> Dict[str, Any]:
    """Recursively sanitize a dictionary by redacting sensitive fields.

    This function maintains backward compatibility with the original API.
    For more control over pattern compilation and caching, use the Sanitizer class directly.

    Args:
        data: The dictionary to sanitize.
        sensitive_patterns: List of substring patterns or compiled regex objects
            to detect sensitive keys. If None, uses default organizational patterns
            plus any patterns loaded from the SENSITIVE_PATTERNS environment variable.

    Returns:
        A new dictionary with sensitive values redacted.
    """
    sanitizer = Sanitizer(sensitive_patterns)
    return sanitizer.sanitize(data)


def get_db_connections(pg_dsn: str, sqlite_path: str) -> Tuple["psycopg2.extensions.connection", sqlite3.Connection]:
    """Establishes connections to PostgreSQL and SQLite databases.

    Note: This function must NOT be called at module level as it would create
    database connections on import, violating the no-module-level-side-effects rule.
    It should only be called inside main() or an explicit initialization function.

    Args:
        pg_dsn: The Data Source Name for the PostgreSQL database.
        sqlite_path: The file path to the SQLite database. Use ':memory:' for in‑memory DB.

    Returns:
        A tuple containing the PostgreSQL connection and the SQLite connection.
    """
    try:
        if psycopg2 is None:
            raise ImportError("psycopg2 is not installed. Install with: pip install psycopg2 (preferred) or pip install psycopg2-binary")
        pg_conn = psycopg2.connect(pg_dsn)
        sq_conn = sqlite3.connect(sqlite_path)
        return pg_conn, sq_conn
    except psycopg2.OperationalError as e:
        logger.exception("PostgreSQL connection error")
        raise RuntimeError("Failed to connect to PostgreSQL") from e
    except sqlite3.OperationalError as e:
        logger.exception("SQLite connection error")
        raise RuntimeError("Failed to connect to SQLite") from e
    except Exception as e:
        logger.exception("Unexpected connection error")
        raise RuntimeError("Failed to establish database connections") from e


@contextmanager
def initialize_connections(pg_dsn: str, sqlite_path: str):
    """Context manager for database connections.

    This is the recommended way to establish database connections.
    It ensures connections are properly closed even if an exception occurs.

    Args:
        pg_dsn: The Data Source Name for the PostgreSQL database.
        sqlite_path: The file path to the SQLite database. Use ':memory:' for in‑memory DB.

    Yields:
        A tuple containing the PostgreSQL connection and the SQLite connection.

    Example:
        with initialize_connections(pg_dsn, sqlite_path) as (pg_conn, sq_conn):
            # Use connections here
            pass
    """
    pg_conn = None
    sq_conn = None
    try:
        pg_conn, sq_conn = get_db_connections(pg_dsn, sqlite_path)
        yield pg_conn, sq_conn
    finally:
        if sq_conn:
            sq_conn.close()
        if pg_conn:
            pg_conn.close()


class TTLCache:
    """Thread-unsafe TTL cache for fetch operations.

    Encapsulates cache storage and TTL configuration to avoid module-level
    mutable state. Provides clear() method for test isolation.
    """

    def __init__(self, ttl_seconds: int = 60) -> None:
        self._ttl_seconds = ttl_seconds
        self._cache: Dict[Tuple, Tuple[Any, float]] = {}

    def get(self, key: Tuple) -> Optional[Any]:
        now = time.time()
        if key in self._cache:
            value, cached_at = self._cache[key]
            if now - cached_at < self._ttl_seconds:
                return value
        return None

    def set(self, key: Tuple, value: Any) -> None:
        self._cache[key] = (value, time.time())

    def clear(self) -> None:
        """Clear all cached entries. Useful for test isolation."""
        self._cache.clear()

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    @ttl_seconds.setter
    def ttl_seconds(self, value: int) -> None:
        self._ttl_seconds = value


# Module-level cache instance for backward compatibility with tests that patch globals.
# Tests can monkeypatch this instance or its methods.
_fetch_cache = TTLCache(ttl_seconds=60)


def clear_cache() -> None:
    """Clear the fetch cache. Provided for test isolation."""
    _fetch_cache.clear()


def _fetch_provider_values(
    sq_conn: sqlite3.Connection,
    providers: List[str],
    table: str,
    column: str,
    cursor: sqlite3.Cursor
) -> Dict[str, int]:
    """Fetch provider-value pairs from a table for the given providers.

    Args:
        sq_conn: The SQLite database connection.
        providers: List of provider names.
        table: The table to query.
        column: The column to retrieve.
        cursor: Reusable cursor to execute the query. Caller must manage cursor lifecycle.

    Returns:
        A dictionary mapping provider to the column value.
    """
    if not providers:
        return {}
    cache_key = (table, column, frozenset(providers))
    cached = _fetch_cache.get(cache_key)
    if cached is not None:
        return cached
    placeholders = ','.join(['?'] * len(providers))
    cursor.execute(
        f"SELECT provider, {column} FROM {table} WHERE provider IN ({placeholders})",
        providers
    )
    result = {row[0]: row[1] for row in cursor.fetchall()}
    _fetch_cache.set(cache_key, result)
    return result


def update_quota(
    sq_conn: sqlite3.Connection,
    provider: str,
    cost: int,
    cursor: Optional[sqlite3.Cursor] = None,
    actor: str = "system",
    approval_ref: Optional[str] = None
) -> None:
    """Decrements the quota for a specific provider in the SQLite database.

    Args:
        sq_conn: The SQLite database connection.
        provider: The name of the enrichment provider.
        cost: The amount to decrement from the quota.
        cursor: Optional cursor to reuse.
        actor: The actor performing the mutation (default: "system").
        approval_ref: Optional reference to the approval for this mutation.

    Raises:
        ValueError: If the provider has insufficient quota or is not found.
    """
    own_cursor = False
    if cursor is None:
        cursor = sq_conn.cursor()
        own_cursor = True
    try:
        # 1. Get remaining before update
        cursor.execute("SELECT remaining FROM quota_ledger WHERE provider = ?", (provider,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Provider '{provider}' not found in quota_ledger")
        
        remaining_before = row[0]
        if remaining_before < cost:
            raise ValueError(f"Insufficient quota for provider '{provider}': {remaining_before} remaining, {cost} required")
        
        # 2. Perform update
        cursor.execute(
            "UPDATE quota_ledger SET remaining = remaining - ? WHERE provider = ? AND remaining >= ?",
            (cost, provider, cost)
        )
        
        remaining_after = remaining_before - cost
        
        # 3. Append-only audit log (Section 30 compliance)
        cursor.execute(
            """INSERT INTO quota_audit_log 
               (provider, cost, remaining_before, remaining_after, timestamp, actor, approval_ref) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (provider, cost, remaining_before, remaining_after, datetime.now(timezone.utc).isoformat(), actor, approval_ref)
        )
    finally:
        if own_cursor:
            cursor.close()


def _check_batch_quota(
    sq_conn: sqlite3.Connection,
    providers_in_batch: List[str],
    providers_needed: List[str],
    cursor: sqlite3.Cursor
) -> None:
    """Validates that all providers in the batch have sufficient quota.

    Fetches quota for all providers in batch to verify configuration,
    fetches cost only for providers that need quota checked, then validates
    in a single pass to avoid redundant iteration and N+1 query patterns.

    Args:
        sq_conn: The SQLite database connection.
        providers_in_batch: All providers referenced in the batch.
        providers_needed: Subset of providers that actually need quota checked.
        cursor: Reusable cursor to execute queries. Caller must manage cursor lifecycle.

    Raises:
        ProviderNotConfiguredError: If a provider is not in quota_ledger.
    """
    quota_map = _fetch_provider_values(sq_conn, providers_in_batch, "quota_ledger", "remaining", cursor)
    cost_map = _fetch_provider_values(sq_conn, providers_needed, "enrichment_costs", "cost", cursor)

    for provider in providers_in_batch:
        if provider not in quota_map:
            raise ProviderNotConfiguredError(f"Provider '{provider}' not configured in quota_ledger")

    for provider in providers_needed:
        cost = cost_map.get(provider, 0)
        remaining = quota_map.get(provider, 0)
        if remaining < cost:
            raise ValueError(f"Insufficient quota for provider '{provider}': {remaining} remaining, {cost} required")