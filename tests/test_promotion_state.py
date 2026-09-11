import pytest
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_canary_passed_not_written_as_proven(tmp_path):
    """CANARY_PASSED must not populate proven_fixes.jsonl."""
    from overnight.self_improver import write_proven_fix
    fix_path = str(tmp_path / "proven_fixes.jsonl")
    
    result = write_proven_fix({"candidate_id": "c1"}, "CANARY_PASSED", fix_path)
    assert result is False
    assert not Path(fix_path).exists()

def test_pending_human_merge_not_written(tmp_path):
    """PENDING_HUMAN_MERGE must not populate proven_fixes.jsonl."""
    from overnight.self_improver import write_proven_fix
    fix_path = str(tmp_path / "proven_fixes.jsonl")
    
    result = write_proven_fix({"candidate_id": "c1"}, "PENDING_HUMAN_MERGE", fix_path)
    assert result is False

def test_merged_writes_proven_fix(tmp_path):
    """MERGED state is the only one that writes proven_fixes.jsonl."""
    from overnight.self_improver import write_proven_fix
    fix_path = str(tmp_path / "proven_fixes.jsonl")
    
    result = write_proven_fix(
        {"candidate_id": "c1", "candidate_hash": "abc123"},
        "MERGED", fix_path
    )
    assert result is True
    assert Path(fix_path).exists()
    content = json.loads(Path(fix_path).read_text().strip())
    assert content["state"] == "MERGED"
    assert content["candidate_hash"] == "abc123"

def test_scorecard_counts_only_merged():
    """Scorecard must ignore non-MERGED states."""
    from overnight.self_improver import compute_applied_fix_count
    entries = [
        {"state": "CANARY_PASSED"},
        {"state": "PENDING_HUMAN_MERGE"},
        {"state": "PI_APPROVED"},
        {"state": "TESTED"},
        {"state": "MERGED"},
        {"state": "REJECTED"},
    ]
    assert compute_applied_fix_count(entries) == 1

def test_invalid_state_rejected():
    """Invalid promotion states are rejected."""
    from overnight.self_improver import write_proven_fix
    with pytest.raises(ValueError, match="Invalid promotion state"):
        write_proven_fix({}, "APPLIED", "/tmp/x.jsonl")
