"""Sanitization pipeline for redacting secrets and high-entropy content.

This module scans string payloads (e.g. process arguments, command lines,
script blocks) for known secret formats via regex, and for generic
high-entropy tokens that may represent unrecognized secrets. Depending on
the field being scanned, matches are either redacted inline or the entire
payload is quarantined and replaced with a reference marker.
"""

import os
import re
import math
import hashlib
from typing import Optional, Dict, Any, Pattern, TypeAlias
from collections import Counter

# Type alias for allowlist pattern dictionaries
AllowlistPatternDict: TypeAlias = Dict[str, Pattern[str]]


# Configurable thresholds loaded from environment variables with validation
def _load_env_float(name: str, default: str, min_val: float, max_val: float) -> float:
    """Loads and validates a float value from an environment variable.

    Args:
        name: The name of the environment variable to read.
        default: The default string value to use if the environment
            variable is not set.
        min_val: The exclusive lower bound for the parsed value.
        max_val: The inclusive upper bound for the parsed value.

    Returns:
        The parsed and validated float value.

    Raises:
        ValueError: If the environment variable's value cannot be parsed
            as a float, or if the parsed value falls outside the
            (min_val, max_val] range.
    """
    raw = os.getenv(name, default)
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a valid float, got '{raw}'")
    if not (min_val < value <= max_val):
        raise ValueError(f"{name} must be in range ({min_val}, {max_val}], got {value}")
    return value


def _load_env_int(name: str, default: str, min_val: int, max_val: int) -> int:
    """Loads and validates an integer value from an environment variable.

    Args:
        name: The name of the environment variable to read.
        default: The default string value to use if the environment
            variable is not set.
        min_val: The inclusive lower bound for the parsed value.
        max_val: The inclusive upper bound for the parsed value.

    Returns:
        The parsed and validated integer value.

    Raises:
        ValueError: If the environment variable's value cannot be parsed
            as an integer, or if the parsed value falls outside the
            [min_val, max_val] range.
    """
    raw = os.getenv(name, default)
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a valid integer, got '{raw}'")
    if not (min_val <= value <= max_val):
        raise ValueError(f"{name} must be in range [{min_val}, {max_val}], got {value}")
    return value


def _load_entropy_threshold() -> float:
    """Loads and validates the Shannon entropy threshold from the environment.

    Returns:
        The entropy threshold above which a token is considered
        high-entropy (a candidate secret).
    """
    return _load_env_float('SANITIZER_ENTROPY_THRESHOLD', '4.5', 0.0, 8.0)


def _load_min_token_length() -> int:
    """Loads and validates the minimum token length from the environment.

    Returns:
        The minimum length a substring must have to be considered a
        candidate token for entropy analysis.
    """
    return _load_env_int('SANITIZER_MIN_TOKEN_LENGTH', '17', 1, 1000)


def _load_analytical_fields() -> set[str]:
    """Loads the set of analytical field paths from the environment.

    Returns:
        A set of field path strings that are subject to the quarantine
        policy for high-entropy payloads.
    """
    default_fields = "process.args,process.command_line,powershell.encoded_command,script.block,bash.command,shell.args,file.contents"
    raw = os.getenv('SANITIZER_ANALYTICAL_FIELDS', default_fields)
    fields = {field.strip() for field in raw.split(',') if field.strip()}
    return fields


def _load_max_quarantine_tokens() -> int:
    """Loads and validates the max tokens to inspect for quarantine.

    Returns:
        The maximum number of tokens to check per payload when
        evaluating the quarantine policy.
    """
    return _load_env_int('SANITIZER_MAX_QUARANTINE_TOKENS', '100', 1, 10000)


def _load_max_quarantine_payload_length() -> int:
    """Loads and validates the max payload length for quarantine scanning.

    Returns:
        The maximum payload length, in characters, that will be scanned
        for quarantine-triggering tokens.
    """
    return _load_env_int('SANITIZER_MAX_QUARANTINE_PAYLOAD_LENGTH', '100000', 1, 10000000)


def _load_diversity_threshold() -> float:
    """Loads and validates the character diversity threshold.

    Returns:
        The minimum ratio of unique characters to token length required
        for a token to pass the fast diversity pre-filter.
    """
    return _load_env_float('SANITIZER_DIVERSITY_THRESHOLD', '0.3', 0.0, 1.0)


# Module-level constants initialized with validation at import time
ENTROPY_THRESHOLD: float = _load_entropy_threshold()
MIN_TOKEN_LENGTH: int = _load_min_token_length()
ANALYTICAL_FIELDS: set[str] = _load_analytical_fields()
MAX_QUARANTINE_TOKENS: int = _load_max_quarantine_tokens()
MAX_QUARANTINE_PAYLOAD_LENGTH: int = _load_max_quarantine_payload_length()
DIVERSITY_THRESHOLD: float = _load_diversity_threshold()


# Regex patterns for known secret formats - single source of truth
# Each entry: (name, pattern, flags) where flags='i' for case-insensitive, '' for case-sensitive
_REGEX_PATTERN_SPECS = [
    ("aws_key", r"AKIA[0-9A-Z]{16}", ""),
    ("github_token", r"ghp_[a-zA-Z0-9]{36}", ""),
    ("jwt", r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}", ""),
    ("ssh_key", r"-----BEGIN [A-Z ]+ PRIVATE KEY-----", ""),
    ("slack_token", r"xox[baprs]-[0-9a-zA-Z]{10,48}", ""),
    ("auth_header", r"Authorization: (Bearer|Basic|Token) [a-zA-Z0-9\._\-]+", "i"),
    ("api_key_param", r"(api_key|apikey|password|passwd|secret|token)=([a-zA-Z0-9]{16,})", "i"),
    ("session_cookie", r"Cookie: (session_id|sid|session)=[a-zA-Z0-9\._\-]+", "i"),
]

# Generate REGEX_RULES dict with inline flags for standalone use
REGEX_RULES: Dict[str, str] = {
    name: (f"(?{flags}:{pattern})" if flags else pattern)
    for name, pattern, flags in _REGEX_PATTERN_SPECS
}


def _neutralize_capturing_groups(pattern: str) -> str:
    """Converts bare capturing groups in a pattern to non-capturing groups.

    This is needed because each pattern is wrapped in its own named group
    when building the combined regex; any bare capturing groups inside the
    original pattern would otherwise shift group numbering. The conversion
    is only applied when the pattern contains at least one capturing group
    and does not already contain an explicit non-capturing group marker
    ('(?:'), to avoid disturbing patterns that already manage their own
    grouping.

    Args:
        pattern: The raw regex pattern to inspect and possibly rewrite.

    Returns:
        The pattern with bare capturing group parens replaced by
        non-capturing group parens, or the original pattern unchanged if
        no conversion is applicable.
    """
    if '(' in pattern and '(?:' not in pattern:
        capturing_group_count = pattern.count('(') - pattern.count('(?:')
        return pattern.replace('(', '(?:', capturing_group_count)
    return pattern


def _build_combined_regex_part(name: str, pattern: str, flags: str) -> str:
    """Builds a single named alternative for the combined regex.

    Args:
        name: The name to use for the named capturing group, matching the
            rule name in `_REGEX_PATTERN_SPECS`.
        pattern: The raw regex pattern for this rule.
        flags: Inline flag string ('i' for case-insensitive, '' for
            case-sensitive).

    Returns:
        A regex fragment scoped with the appropriate inline flag and
        wrapped in a named group, suitable for joining with '|' into a
        combined pattern.
    """
    normalized_pattern = _neutralize_capturing_groups(pattern)
    inline_flags = flags if flags else '-i'
    return f"(?{inline_flags}:(?P<{name}>{normalized_pattern}))"


# Build combined regex with named groups for single-pass scanning
_COMBINED_REGEX_PARTS = [
    _build_combined_regex_part(name, pattern, flags)
    for name, pattern, flags in _REGEX_PATTERN_SPECS
]

_COMBINED_REGEX_PATTERN = "|".join(_COMBINED_REGEX_PARTS)
_COMBINED_REGEX: Pattern[str] = re.compile(_COMBINED_REGEX_PATTERN)


# Allowlist patterns for known safe high-entropy strings
# These prevent false positives on hashes, UUIDs, and other legitimate identifiers
ALLOWLIST_PATTERNS: Dict[str, str] = {
    "sha256": r"^[a-fA-F0-9]{64}$",
    "sha1": r"^[a-fA-F0-9]{40}$",
    "md5": r"^[a-fA-F0-9]{32}$",
    "uuid": r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
}

ALLOWLIST_PATTERNS_COMPILED: AllowlistPatternDict = {
    k: re.compile(v) for k, v in ALLOWLIST_PATTERNS.items()
}

# Pre-compiled token pattern for entropy analysis (uses configurable MIN_TOKEN_LENGTH)
TOKEN_PATTERN: Pattern[str] = re.compile(rf'[a-zA-Z0-9+/=]{{{MIN_TOKEN_LENGTH},}}')


def calculate_entropy(data: str) -> float:
    """Calculates the Shannon entropy of a given string.

    Args:
        data: The input string to analyze.

    Returns:
        float: The calculated Shannon entropy. Returns 0.0 for empty string.

    Raises:
        TypeError: If data is not a string.
    """
    if not isinstance(data, str):
        raise TypeError(f"Expected str, got {type(data).__name__}")
    if not data:
        return 0.0
    counts = Counter(data)
    length = len(data)
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy += -probability * math.log(probability, 2)
    return entropy


def _check_allowlist(token: str) -> bool:
    """Checks if a token matches any allowlisted pattern.

    Args:
        token: The token to check against allowlist patterns.

    Returns:
        True if token matches an allowlist pattern, False otherwise.
    """
    return any(
        pattern.match(token) is not None
        for pattern in ALLOWLIST_PATTERNS_COMPILED.values()
    )


def _quick_diversity_check(token: str) -> bool:
    """Fast pre-filter: checks if token has sufficient character diversity.

    Args:
        token: The token to check.

    Returns:
        True if token passes diversity threshold, False otherwise.
    """
    unique_chars = len(set(token))
    return (unique_chars / len(token)) >= DIVERSITY_THRESHOLD


def _should_quarantine(token: str) -> bool:
    """Checks if a token should trigger quarantine (high entropy, not allowlisted).

    Args:
        token: The token to evaluate.

    Returns:
        True if token has high entropy and is not allowlisted.
    """
    return calculate_entropy(token) > ENTROPY_THRESHOLD and not _check_allowlist(token)


def reload_allowlist() -> None:
    """Reloads and recompiles allowlist patterns from ALLOWLIST_PATTERNS.

    Call this function after modifying ALLOWLIST_PATTERNS at runtime
    to keep ALLOWLIST_PATTERNS_COMPILED in sync.
    """
    global ALLOWLIST_PATTERNS_COMPILED
    ALLOWLIST_PATTERNS_COMPILED = {
        k: re.compile(v) for k, v in ALLOWLIST_PATTERNS.items()
    }


def reload_analytical_fields() -> None:
    """Reloads analytical fields from environment variable.

    Call this function after modifying SANITIZER_ANALYTICAL_FIELDS at runtime
    to keep ANALYTICAL_FIELDS in sync.
    """
    global ANALYTICAL_FIELDS
    ANALYTICAL_FIELDS = _load_analytical_fields()


def redact_regex_patterns(payload: str, metadata: Dict[str, Any]) -> str:
    """Redacts sensitive patterns using combined regex in single pass.

    Args:
        payload: The input string to redact.
        metadata: Dictionary to update with redaction counts.

    Returns:
        The payload with regex patterns redacted.
    """
    redaction_count = 0

    def redact_match(match: re.Match[str]) -> str:
        nonlocal redaction_count
        redaction_count += 1
        return f"[REDACTED_{match.lastgroup.upper()}]" if match.lastgroup else match.group(0)

    result = _COMBINED_REGEX.sub(redact_match, payload)
    metadata["regex_redaction_count"] = redaction_count
    return result


def apply_quarantine_policy(payload: str, field_path: Optional[str], metadata: Dict[str, Any]) -> str:
    """Applies quarantine policy for analytical fields with high-entropy content.

    Args:
        payload: The input string to evaluate.
        field_path: Optional field path to determine quarantine behavior.
        metadata: Dictionary to update with quarantine action.

    Returns:
        The payload, or "[QUARANTINED_REF]" if quarantine is triggered.
    """
    is_analytical = field_path in ANALYTICAL_FIELDS
    if not is_analytical:
        return payload

    if len(payload) > MAX_QUARANTINE_PAYLOAD_LENGTH:
        metadata["quarantine_skipped_reason"] = "payload_too_large"
        return payload

    tokens_checked = 0
    for match in TOKEN_PATTERN.finditer(payload):
        if tokens_checked >= MAX_QUARANTINE_TOKENS:
            metadata["quarantine_skipped_reason"] = "max_tokens_reached"
            break

        token = match.group()
        tokens_checked += 1

        if not _quick_diversity_check(token):
            continue

        if _should_quarantine(token):
            metadata["sanitization_action"] = "quarantine_ref"
            metadata["quarantine_reason"] = "high_entropy_analytical_payload"
            return "[QUARANTINED_REF]"

    return payload


def detect_high_entropy_tokens(payload: str, metadata: Dict[str, Any]) -> str:
    """Redacts high-entropy tokens inline using single-pass substitution.

    Args:
        payload: The input string to analyze.
        metadata: Dictionary to update with entropy redaction counts.

    Returns:
        The payload with high-entropy tokens redacted.
    """
    def replace_token(match: re.Match[str]) -> str:
        token = match.group()
        if _should_quarantine(token):
            metadata["entropy_redaction_count"] += 1
            return "[REDACTED_HIGH_ENTROPY]"
        return token

    return TOKEN_PATTERN.sub(replace_token, payload)


def build_metadata(payload: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Builds final metadata including action determination and payload hash.

    Args:
        payload: The sanitized payload string.
        metadata: The metadata dictionary to finalize.

    Returns:
        The completed metadata dictionary.
    """
    if "sanitization_action" not in metadata:
        if not metadata["regex_redaction_count"] and not metadata["entropy_redaction_count"]:
            metadata["sanitization_action"] = "preserve_allowlisted"
        else:
            metadata["sanitization_action"] = "redact_inline"

    metadata["redaction_manifest_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    return metadata


def sanitize_payload(payload: str, field_path: Optional[str] = None) -> Dict[str, Any]:
    """Sanitizes a payload by redacting sensitive patterns and high-entropy strings.

    Args:
        payload: The raw string content to be sanitized.
        field_path: An optional identifier for the field type, used to determine
            if the payload should be quarantined.

    Returns:
        A dictionary containing the sanitized 'payload' string and a 'metadata'
        dictionary detailing the sanitization actions taken.
    """
    metadata = {"sanitizer_version": "11.6.0", "regex_redaction_count": 0, "entropy_redaction_count": 0}

    # Pass 1: Regex Redaction (single pass with combined regex)
    payload = redact_regex_patterns(payload, metadata)

    # Pass 2: Quarantine Policy Check
    payload = apply_quarantine_policy(payload, field_path, metadata)

    # Early return if quarantined
    if payload == "[QUARANTINED_REF]":
        metadata = build_metadata(payload, metadata)
        return {"payload": payload, "metadata": metadata}

    # Pass 3: High-Entropy Token Detection and Redaction
    payload = detect_high_entropy_tokens(payload, metadata)

    # Build final metadata
    metadata = build_metadata(payload, metadata)

    return {"payload": payload, "metadata": metadata}
