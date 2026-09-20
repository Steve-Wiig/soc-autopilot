import json
import logging
import os
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION (Externalized from hardcoded values)
# ============================================================

def _get_db_config() -> Dict[str, str]:
    """Load database configuration from environment variables."""
    return {
        "dbname": os.getenv("SOC_DB_NAME", "soc_memory"),
        "user": os.getenv("SOC_DB_USER", "orchestrator"),
        "password": os.getenv("SOC_DB_PASSWORD", ""),
        "host": os.getenv("SOC_DB_HOST", "localhost"),
        "port": os.getenv("SOC_DB_PORT", "5432"),
    }


def get_pg_conn(conn: Optional[psycopg2.extensions.connection] = None) -> psycopg2.extensions.connection:
    """
    Get or create a PostgreSQL connection.
    
    Args:
        conn: Optional existing connection. If None or closed, creates new one.
    
    Returns:
        Active database connection.
    
    Note:
        Caller is responsible for managing connection lifecycle.
        This function does NOT cache connections at module level.
    """
    if conn is not None and not conn.closed:
        return conn
    
    config = _get_db_config()
    return psycopg2.connect(**config)


# ============================================================
# SANITIZATION (Section 34 compliance)
# ============================================================

# High-entropy threshold: strings with entropy > 4.5 bits/char are likely secrets
_HIGH_ENTROPY_THRESHOLD = 4.5

# Patterns that indicate secrets (not IOCs)
_SECRET_PATTERNS = [
    re.compile(r'^(?:sk-|pk-|key-|token-|Bearer\s+)[A-Za-z0-9_\-]{20,}$', re.IGNORECASE),  # API keys
    re.compile(r'^eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$', re.IGNORECASE),  # JWTs
    re.compile(r'^[A-Za-z0-9+/]{40,}={0,2}$'),  # Base64-encoded secrets
]


def _calculate_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string (bits per character)."""
    if not s:
        return 0.0
    
    from collections import Counter
    counts = Counter(s)
    length = len(s)
    entropy = 0.0
    
    for count in counts.values():
        probability = count / length
        if probability > 0:
            entropy -= probability * (probability and __import__('math').log2(probability))
    
    return entropy


def sanitize_ioc(value: str, ioc_type: str) -> Optional[str]:
    """
    Validate and sanitize an IOC value before persistence.
    
    Args:
        value: Raw IOC string to validate.
        ioc_type: Type of IOC (ipv4, domain, url, sha256, email).
    
    Returns:
        Sanitized IOC string if valid, None if rejected.
    
    Rejects:
        - High-entropy strings (likely secrets/API keys)
        - Strings matching secret patterns
        - Values that don't match expected IOC format
    """
    if not value or not isinstance(value, str):
        return None
    
    value = value.strip()
    
    # Reject high-entropy strings (likely secrets)
    entropy = _calculate_entropy(value)
    if entropy > _HIGH_ENTROPY_THRESHOLD and len(value) > 20:
        logger.warning(f"Rejected high-entropy IOC candidate (entropy={entropy:.2f}): {value[:20]}...")
        return None
    
    # Reject strings matching secret patterns
    for pattern in _SECRET_PATTERNS:
        if pattern.match(value):
            logger.warning(f"Rejected secret-like IOC candidate: {value[:20]}...")
            return None
    
    # Validate format based on IOC type
    if ioc_type == "ipv4":
        # Basic IPv4 validation
        parts = value.split('.')
        if len(parts) != 4:
            return None
        try:
            if not all(0 <= int(part) <= 255 for part in parts):
                return None
        except ValueError:
            return None
    
    elif ioc_type == "sha256":
        # SHA256 must be exactly 64 hex characters
        if len(value) != 64 or not re.match(r'^[a-fA-F0-9]{64}$', value):
            return None
    
    elif ioc_type == "email":
        # Basic email validation
        if '@' not in value or '.' not in value.split('@')[-1]:
            return None
    
    elif ioc_type == "domain":
        # Domain must have at least one dot and valid characters
        if '.' not in value or not re.match(r'^[a-z0-9.-]+\.[a-z]{2,}$', value, re.IGNORECASE):
            return None
    
    elif ioc_type == "url":
        # URL must start with http:// or https://
        if not value.lower().startswith(('http://', 'https://')):
            return None
    
    return value


# ============================================================
# IOC TYPES AND PATTERNS
# ============================================================

class IOCType(Enum):
    IPV4 = "ipv4"
    DOMAIN = "domain"
    URL = "url"
    SHA256 = "sha256"
    EMAIL = "email"


_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOMAIN_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

_IOC_PATTERNS = [
    (IOCType.IPV4, _IPV4_RE),
    (IOCType.DOMAIN, _DOMAIN_RE),
    (IOCType.URL, _URL_RE),
    (IOCType.SHA256, _SHA256_RE),
    (IOCType.EMAIL, _EMAIL_RE),
]


# ============================================================
# TEXT EXTRACTION (Bounded to prevent memory issues)
# ============================================================

# Known alert fields to extract (prevents unbounded recursion)
_ALERT_TEXT_FIELDS = {'description', 'message', 'summary', 'details', 'text', 'content', 'body'}

# Maximum text length to prevent regex catastrophic backtracking
_MAX_TEXT_LENGTH = 100_000  # 100KB


def extract_iocs_from_text(text: str, max_text_length: int = _MAX_TEXT_LENGTH) -> Dict[IOCType, set]:
    """
    Extract IOCs from text using regex patterns.
    
    Args:
        text: Text to search for IOCs. If valid JSON, extracts text fields selectively.
        max_text_length: Maximum text length to process (prevents memory issues).
    
    Returns:
        Dictionary mapping IOCType to set of matched values.
    """
    def _extract_text_fields(obj: Any, depth: int = 0) -> str:
        """Recursively extract text from dict/list, targeting known alert fields."""
        if depth > 10:  # Prevent infinite recursion
            return ''
        
        if isinstance(obj, dict):
            text_parts = []
            for key in _ALERT_TEXT_FIELDS:
                if key in obj and isinstance(obj[key], str):
                    text_parts.append(obj[key])
            for value in obj.values():
                text_parts.append(_extract_text_fields(value, depth + 1))
            return ' '.join(text_parts)
        elif isinstance(obj, list):
            return ' '.join(_extract_text_fields(item, depth + 1) for item in obj)
        elif isinstance(obj, str):
            return obj
        return ''

    if text and text[0] in ('{', '['):
        try:
            data = json.loads(text)
            text = _extract_text_fields(data)
        except (json.JSONDecodeError, TypeError):
            pass

    # Enforce text length limit
    if len(text) > max_text_length:
        logger.warning(f"Text truncated from {len(text)} to {max_text_length} characters")
        text = text[:max_text_length]

    matches_by_type: Dict[IOCType, set] = {ioc_type: set() for ioc_type in IOCType}
    for ioc_type, pattern in _IOC_PATTERNS:
        for match in pattern.finditer(text):
            matches_by_type[ioc_type].add(match.group(0))
    return matches_by_type


def deduplicate_iocs(matches_by_type: Dict[IOCType, set]) -> List[Tuple[str, str, str, datetime]]:
    """
    Deduplicate IOCs and prepare for persistence.
    
    Args:
        matches_by_type: Dictionary mapping IOCType to set of matched values.
    
    Returns:
        List of tuples (value, type, enrichment_status, first_seen).
    """
    seen = datetime.now(timezone.utc)
    extracted: List[Tuple[str, str, str, datetime]] = []
    for ioc_type, matches in matches_by_type.items():
        for match in matches:
            # Sanitize before adding to extraction list
            sanitized = sanitize_ioc(match, ioc_type.value)
            if sanitized:
                extracted.append((sanitized, ioc_type.value, "pending", seen))
    return extracted


def persist_iocs(
    extracted: List[Tuple[str, str, str, datetime]],
    conn: Optional[psycopg2.extensions.connection] = None
) -> None:
    """
    Persist IOCs to PostgreSQL with audit trail.
    
    Args:
        extracted: List of tuples (value, type, enrichment_status, first_seen).
        conn: Optional database connection. If None, creates new one.
    
    Raises:
        RuntimeError: If database operations fail.
    """
    if not extracted:
        return

    should_close = False
    if conn is None:
        conn = get_pg_conn()
        should_close = True

    try:
        cur = conn.cursor()

        query = """
            WITH ins AS (
                INSERT INTO iocs (value, type, enrichment_status, first_seen)
                VALUES %s
                ON CONFLICT (value) DO UPDATE SET last_seen = EXCLUDED.first_seen
                RETURNING value, type, first_seen
            )
            INSERT INTO ioc_audit (value, type, action, timestamp)
            SELECT value, type, 'insert', first_seen FROM ins;
        """
        execute_values(cur, query, extracted)

        conn.commit()
        cur.close()
    finally:
        if should_close and conn is not None:
            conn.close()


def audit_iocs(alert_id: str, ioc_count: int, timestamp: datetime) -> None:
    """
    Log IOC extraction audit information.
    
    Args:
        alert_id: Alert identifier.
        ioc_count: Number of IOCs extracted.
        timestamp: Extraction timestamp.
    """
    logger.info(
        "IOC extraction audit: alert_id=%s ioc_count=%s timestamp=%s",
        alert_id,
        ioc_count,
        timestamp.isoformat(),
    )


def extract_iocs(
    sanitized_alert_json: Dict[str, Any],
    conn: Optional[psycopg2.extensions.connection] = None
) -> int:
    """
    Extracts IOCs from sanitized alert payloads and persists to PostgreSQL.
    
    Compliant with soc-autopilot Section 30 (audit) and Section 34 (sanitization).
    
    Args:
        sanitized_alert_json: A dictionary containing the alert data to be parsed.
        conn: Optional database connection. If None, creates new one.
    
    Returns:
        int: 0 if successful or no IOCs found.
    
    Raises:
        RuntimeError: If extraction or database operations fail.
    """
    try:
        serialized = json.dumps(sanitized_alert_json, ensure_ascii=False)
        matches_by_type = extract_iocs_from_text(serialized)
        extracted = deduplicate_iocs(matches_by_type)

        if not extracted:
            return 0

        alert_id = _extract_alert_id(sanitized_alert_json)
        ioc_count = len(extracted)
        seen = datetime.now(timezone.utc)

        persist_iocs(extracted, conn=conn)
        audit_iocs(alert_id, ioc_count, seen)

        return 0

    except psycopg2.Error as e:
        logger.exception("Database error")
        raise RuntimeError("Database error") from e
    except (TypeError, ValueError, AttributeError, KeyError) as e:
        logger.exception("Extraction error")
        raise RuntimeError("Extraction failed") from e


def _extract_alert_id(alert_json: Dict[str, Any]) -> str:
    """Extract alert ID from sanitized alert JSON using common field names."""
    for key in ("alert_id", "alertId", "id", "alert_id_str"):
        if key in alert_json and alert_json[key]:
            return str(alert_json[key])
    return "unknown"


if __name__ == "__main__":
    result = extract_iocs({})
    print(result)
