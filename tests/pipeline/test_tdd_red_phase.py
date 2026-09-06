"""
Regression test for Improvement #2: TDD Red Phase Verification

BEFORE: Generated TDD tests were accepted without verifying they fail.
PROBLEM: Vacuous tests (always pass) create false-positive fixes.
CHANGE: Run pytest on the generated test. If it passes immediately,
        reject it. Only accept tests that fail (Red Backlog Drainonfirmed).
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def tdd_env(tmp_path):
    (tmp_path / "overnight").mkdir()
    (tmp_path / "tests").mkdir()
    src = tmp_path / "dummy_module.py"
    src.write_text("def dummy():\n    return 42\n")
    return tmp_path, src


def test_vacuous_tdd_test_rejected(tdd_env):
    """A TDD test that passes immediately must be rejected (not red).

    Flow: baseline FAILS -> TDD generated -> red Backlog Drainheck PASSES -> reject test.
    """
    tmp_path, src = tdd_env

    issue = {"category": "correctness", "description": "dummy bug"}
    fake_test = "def test_always_passes():\n    assert True\n"

    call_count = {"n": 0}

    def mock_run_pytest(targets, timeout=60):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "AssertionError: baseline failure"  # Baseline FAILS -> proceed to TDD
        return None  # Red Backlog Drainheck PASSES -> test is vacuous -> reject

    with patch("overnight.self_improver.ROOT", tmp_path), \
         patch("overnight.self_improver._get_repo_fingerprint", return_value="unique-test-fp"), \
         patch("overnight.self_improver.run_pytest", side_effect=mock_run_pytest), \
         patch("overnight.self_improver.is_ast_defeated", return_value=False), \
         patch("overnight.self_improver._generate_tdd_test", return_value=fake_test):

        from overnight.self_improver import apply_auto_fix
        apply_auto_fix(src, issue, api_keys={})

    # The vacuous test file must have been deleted
    test_file = tmp_path / "tests" / "test_tdd_auto_dummy_module.py"
    assert not test_file.exists(), "Vacuous TDD test should have been rejected and deleted"


def test_valid_tdd_test_accepted(tdd_env):
    """A TDD test that fails (red phase) must be accepted as acceptance criteria.

    Flow: baseline FAILS -> TDD generated -> red Backlog Drainheck FAILS -> keep test.
    """
    tmp_path, src = tdd_env

    issue = {"category": "correctness", "description": "dummy bug"}
    fake_test = "def test_should_fail():\n    assert False\n"

    call_count = {"n": 0}

    def mock_run_pytest(targets, timeout=60):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "AssertionError: baseline failure"  # Baseline FAILS -> proceed to TDD
        return "AssertionError: expected failure"  # Red phase FAILS -> test is valid -> keep

    with patch("overnight.self_improver.ROOT", tmp_path), \
         patch("overnight.self_improver._get_repo_fingerprint", return_value="unique-test-fp"), \
         patch("overnight.self_improver.run_pytest", side_effect=mock_run_pytest), \
         patch("overnight.self_improver.is_ast_defeated", return_value=False), \
         patch("overnight.self_improver._generate_tdd_test", return_value=fake_test), \
         patch("overnight.self_improver.generate", return_value=None):  # Stop generation loop

        from overnight.self_improver import apply_auto_fix
        apply_auto_fix(src, issue, api_keys={})

    # The valid test file must still exist (not deleted)
    test_file = tmp_path / "tests" / "test_tdd_auto_dummy_module.py"
    assert test_file.exists(), "Valid TDD test (red Backlog Drainonfirmed) should be kept"
