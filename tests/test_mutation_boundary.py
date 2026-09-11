import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_exact_match_single():
    from engine.multi_file_patcher import _find_patch_location_strict
    source = "def foo():\n    return 1"
    search = "def foo():"
    location = _find_patch_location_strict(source, search)
    assert location == 0

def test_exact_match_multiple_rejected():
    from engine.multi_file_patcher import _find_patch_location_strict
    source = "def foo():\n    pass\n\ndef foo():\n    pass"
    search = "def foo():"
    with pytest.raises(ValueError, match="AMBIGUOUS PATCH"):
        _find_patch_location_strict(source, search)

def test_normalized_match():
    from engine.multi_file_patcher import _find_patch_location_strict
    source = "def foo():\n    return    1"
    search = "def foo():\n    return 1"
    location = _find_patch_location_strict(source, search)
    assert location >= 0

def test_no_match_rejected():
    from engine.multi_file_patcher import _find_patch_location_strict
    source = "def bar():\n    return 2"
    search = "def foo():"
    with pytest.raises(ValueError, match="PATCH LOCATION NOT FOUND"):
        _find_patch_location_strict(source, search)

def test_path_traversal_rejected(tmp_path):
    from engine.multi_file_patcher import validate_mutation_target
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="escapes repository"):
        validate_mutation_target(repo, set(), Path("../outside.py"))

def test_symlink_escape_rejected(tmp_path):
    from engine.multi_file_patcher import validate_mutation_target
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("evil")
    link = repo / "link.py"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes repository"):
        validate_mutation_target(repo, set(), Path("link.py"))

def test_ambiguous_fuzzy_rejected():
    from engine.multi_file_patcher import _find_patch_location_strict
    source = "def foo():\n    # similar\n    pass\n\ndef bar():\n    # similar\n    pass"
    search = "def foo():\n    # similar"
    location = _find_patch_location_strict(source, search)
    assert location == 0
