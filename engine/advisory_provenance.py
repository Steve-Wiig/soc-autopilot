"""
Deterministic provenance tracking for autonomous advisories.
Ensures CURRENT SOURCE > HISTORICAL LLM FINDING.
"""
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict

# Reason codes returned by validate_advisory_provenance().
# Kept as string constants (rather than an Enum) so the values remain
# plain strings in the returned dict, matching prior behavior exactly.
REASON_MISSING_FILE_REFERENCE = "MISSING_FILE_REFERENCE"
REASON_FILE_NOT_FOUND = "FILE_NOT_FOUND"
REASON_MISSING_PROVENANCE = "MISSING_PROVENANCE"
REASON_SOURCE_CHANGED = "SOURCE_CHANGED"
REASON_PROVENANCE_MATCH = "PROVENANCE_MATCH"


class ProvenanceValidationResult(TypedDict):
    """Shape of the dict returned by validate_advisory_provenance()."""
    is_current: bool
    reason: str
    current_hash: Optional[str]


def compute_source_hash(file_path: Path) -> Optional[str]:
    """
    Compute the SHA-256 hash of a source file for provenance tracking.

    Args:
        file_path: Path to the source file to hash.

    Returns:
        The hex-encoded SHA-256 digest of the file's contents, or None if
        the file does not exist or cannot be read (any exception during
        reading is intentionally swallowed so callers can treat "missing"
        and "unreadable" files the same way).
    """
    try:
        if not file_path.exists():
            return None
        return hashlib.sha256(file_path.read_bytes()).hexdigest()
    except Exception:
        return None


def validate_advisory_provenance(
    advisory: Dict[str, Any],
    base_path: Path
) -> ProvenanceValidationResult:
    """
    Validate an advisory's recorded provenance against the current source file.

    Ensures CURRENT SOURCE > HISTORICAL LLM FINDING by comparing the hash
    recorded on the advisory (at the time it was generated) against the
    hash of the source file as it exists on disk right now.

    Args:
        advisory: Advisory dict expected to contain either a "file" or
            "file_path" key (relative path to the source file) and,
            optionally, a "source_hash" key with the previously recorded
            SHA-256 hash of that file.
        base_path: Base directory that "file"/"file_path" is relative to.

    Returns:
        A ProvenanceValidationResult dict with:
        - is_current: True only if the advisory's recorded hash matches
          the current on-disk hash of the referenced file.
        - reason: One of MISSING_FILE_REFERENCE, FILE_NOT_FOUND,
          MISSING_PROVENANCE, SOURCE_CHANGED, or PROVENANCE_MATCH,
          explaining why the advisory is considered current or stale.
        - current_hash: The current SHA-256 hash of the source file, or
          None if the file reference is missing or the file was not found.
    """
    file_relative_path = advisory.get("file") or advisory.get("file_path")
    if not file_relative_path:
        return {
            "is_current": False,
            "reason": REASON_MISSING_FILE_REFERENCE,
            "current_hash": None
        }

    file_path = base_path / file_relative_path
    current_hash = compute_source_hash(file_path)

    if current_hash is None:
        return {
            "is_current": False,
            "reason": REASON_FILE_NOT_FOUND,
            "current_hash": None
        }

    recorded_hash = advisory.get("source_hash")

    if not recorded_hash:
        return {
            "is_current": False,
            "reason": REASON_MISSING_PROVENANCE,
            "current_hash": current_hash
        }

    if recorded_hash != current_hash:
        return {
            "is_current": False,
            "reason": REASON_SOURCE_CHANGED,
            "current_hash": current_hash
        }

    return {
        "is_current": True,
        "reason": REASON_PROVENANCE_MATCH,
        "current_hash": current_hash
    }
