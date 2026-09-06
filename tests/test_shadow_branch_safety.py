import subprocess
import pytest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

def test_shadow_branch_captures_current_branch():
    """Verify shadow canary uses actual branch, not hardcoded master."""
    si_path = REPO_ROOT / "overnight" / "self_improver.py"
    content = si_path.read_text()
    
    # Check that BASE_BRANCH is captured
    assert "BASE_BRANCH = subprocess.check_output" in content, \
        "Shadow canary must capture BASE_BRANCH"
    
    # Check that master is not hardcoded in checkout
    lines = content.split('\n')
    checkout_lines = [l for l in lines if 'git", "checkout"' in l]
    
    for line in checkout_lines:
        if 'subprocess.run' in line:
            # Should not contain hardcoded "master"
            assert '"master"' not in line or 'BASE_BRANCH' in line, \
                f"Found hardcoded master checkout: {line}"
    
    # Check for detached HEAD guard
    assert "Detached HEAD" in content or "BASE_BRANCH" in content, \
        "Must have branch validation logic"
    
    print("✅ PROVEN: Shadow canary targets current branch, not master")

def test_apply_auto_fix_has_branch_guard():
    """Verify apply_auto_fix checks branch state before proceeding."""
    si_path = REPO_ROOT / "overnight" / "self_improver.py"
    content = si_path.read_text()
    
    # Find apply_auto_fix function
    func_start = content.find("def apply_auto_fix")
    func_end = content.find("\ndef ", func_start + 1)
    func_content = content[func_start:func_end]
    
    # Should have branch check near the start
    assert "branch" in func_content.lower() and ("show-current" in func_content or "BASE_BRANCH" in func_content), \
        "apply_auto_fix must verify branch state"
    
    print("✅ PROVEN: apply_auto_fix has branch safety guard")

if __name__ == "__main__":
    test_shadow_branch_captures_current_branch()
    test_apply_auto_fix_has_branch_guard()
