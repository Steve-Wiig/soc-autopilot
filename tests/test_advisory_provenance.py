"""
Tests for deterministic advisory provenance validation.
Proves CURRENT SOURCE > HISTORICAL LLM FINDING invariant.
"""
import json
import pytest
import tempfile
from pathlib import Path
from engine.advisory_provenance import compute_source_hash, validate_advisory_provenance

@pytest.fixture
def temp_source_file():
    """Create a temporary source file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("# Test source file\nprint('hello')\n")
        path = Path(f.name)
    yield path
    path.unlink()

def test_matching_hash_remains_eligible(temp_source_file):
    """Prove: matching source hash remains eligible as current evidence."""
    current_hash = compute_source_hash(temp_source_file)
    advisory = {
        "file": str(temp_source_file),
        "source_hash": current_hash
    }
    
    result = validate_advisory_provenance(advisory, temp_source_file.parent)
    
    assert result["is_current"] is True
    assert result["reason"] == "PROVENANCE_MATCH"
    assert result["current_hash"] == current_hash

def test_changed_hash_becomes_stale(temp_source_file):
    """Prove: changed source hash becomes stale/historical."""
    old_hash = "old_hash_that_doesnt_match"
    advisory = {
        "file": str(temp_source_file),
        "source_hash": old_hash
    }
    
    result = validate_advisory_provenance(advisory, temp_source_file.parent)
    
    assert result["is_current"] is False
    assert result["reason"] == "SOURCE_CHANGED"

def test_missing_source_becomes_historical():
    """Prove: missing source file becomes historical."""
    advisory = {
        "file": "nonexistent_file.py",
        "source_hash": "some_hash"
    }
    
    result = validate_advisory_provenance(advisory, Path("/tmp"))
    
    assert result["is_current"] is False
    assert result["reason"] == "FILE_NOT_FOUND"

def test_missing_provenance_cannot_become_current(temp_source_file):
    """Prove: missing provenance cannot silently become current."""
    advisory = {
        "file": str(temp_source_file)
        # No source_hash field
    }
    
    result = validate_advisory_provenance(advisory, temp_source_file.parent)
    
    assert result["is_current"] is False
    assert result["reason"] == "MISSING_PROVENANCE"

def test_missing_file_reference():
    """Prove: missing file reference is rejected."""
    advisory = {
        "advisory_notes": "some finding"
        # No file or file_path field
    }
    
    result = validate_advisory_provenance(advisory, Path("/tmp"))
    
    assert result["is_current"] is False
    assert result["reason"] == "MISSING_FILE_REFERENCE"

def test_source_modification_invalidates_advisory(temp_source_file):
    """Prove: modifying source invalidates advisory with old hash."""
    # Create advisory with initial hash
    initial_hash = compute_source_hash(temp_source_file)
    advisory = {
        "file": str(temp_source_file),
        "source_hash": initial_hash
    }
    
    # Verify it's current
    result1 = validate_advisory_provenance(advisory, temp_source_file.parent)
    assert result1["is_current"] is True
    
    # Modify the source file
    temp_source_file.write_text("# Modified source\nprint('changed')\n")
    
    # Now advisory should be stale
    result2 = validate_advisory_provenance(advisory, temp_source_file.parent)
    assert result2["is_current"] is False
    assert result2["reason"] == "SOURCE_CHANGED"

def test_compute_source_hash_deterministic(temp_source_file):
    """Prove: hash computation is deterministic."""
    hash1 = compute_source_hash(temp_source_file)
    hash2 = compute_source_hash(temp_source_file)
    
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 produces 64 hex chars

def test_compute_source_hash_nonexistent_file():
    """Prove: hash of nonexistent file returns None."""
    result = compute_source_hash(Path("/nonexistent/file.py"))
    assert result is None

def test_file_path_key_alternative(temp_source_file):
    """Prove: both 'file' and 'file_path' keys are supported."""
    current_hash = compute_source_hash(temp_source_file)
    
    # Test with 'file' key
    advisory1 = {"file": str(temp_source_file), "source_hash": current_hash}
    result1 = validate_advisory_provenance(advisory1, temp_source_file.parent)
    assert result1["is_current"] is True
    
    # Test with 'file_path' key
    advisory2 = {"file_path": str(temp_source_file), "source_hash": current_hash}
    result2 = validate_advisory_provenance(advisory2, temp_source_file.parent)
    assert result2["is_current"] is True
