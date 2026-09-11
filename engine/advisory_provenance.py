"""
Deterministic provenance tracking for autonomous advisories.
Ensures CURRENT SOURCE > HISTORICAL LLM FINDING.
"""
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any

def compute_source_hash(file_path: Path) -> Optional[str]:
    """Compute SHA-256 hash of a source file for provenance tracking."""
    try:
        if not file_path.exists():
            return None
        return hashlib.sha256(file_path.read_bytes()).hexdigest()
    except Exception:
        return None

def validate_advisory_provenance(
    advisory: Dict[str, Any],
    base_path: Path
) -> Dict[str, Any]:
    """
    Validate advisory provenance against current source.
    
    Returns dict with:
    - is_current: bool (True if advisory matches current source)
    - reason: str (why it's current or stale)
    - current_hash: Optional[str] (current source hash if file exists)
    """
    file_rel = advisory.get("file") or advisory.get("file_path")
    if not file_rel:
        return {
            "is_current": False,
            "reason": "MISSING_FILE_REFERENCE",
            "current_hash": None
        }
    
    file_path = base_path / file_rel
    current_hash = compute_source_hash(file_path)
    
    if current_hash is None:
        return {
            "is_current": False,
            "reason": "FILE_NOT_FOUND",
            "current_hash": None
        }
    
    recorded_hash = advisory.get("source_hash")
    
    if not recorded_hash:
        return {
            "is_current": False,
            "reason": "MISSING_PROVENANCE",
            "current_hash": current_hash
        }
    
    if recorded_hash != current_hash:
        return {
            "is_current": False,
            "reason": "SOURCE_CHANGED",
            "current_hash": current_hash
        }
    
    return {
        "is_current": True,
        "reason": "PROVENANCE_MATCH",
        "current_hash": current_hash
    }
