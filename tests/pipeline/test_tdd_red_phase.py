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


def test_valid_tdd_test_accepted_during_lifecycle(tdd_env):
    """A valid TDD artifact exists during RED validation and is cleaned
    up when apply_auto_fix() terminates.
    """
    tmp_path, src = tdd_env

    issue = {"category": "correctness", "description": "dummy bug"}
    fake_test = "def test_should_fail():\n    assert False\n"

    call_count = {"n": 0}
    cleanup = {
        "called": False,
        "path": None,
        "existed_before": False,
    }

    def mock_run_pytest(targets, timeout=60):
        call_count["n"] += 1

        if call_count["n"] == 1:
            return "AssertionError: baseline failure"

        test_file = tmp_path / "tests" / "test_tdd_auto_dummy_module.py"

        assert test_file.exists(), (
            "Valid TDD artifact must exist during RED-phase validation"
        )

        return "AssertionError: expected failure"

    from overnight import self_improver

    real_cleanup = self_improver._cleanup_tdd_artifact

    def observing_cleanup(path):
        cleanup["called"] = True
        cleanup["path"] = path
        cleanup["existed_before"] = (
            path is not None and path.exists()
        )
        real_cleanup(path)

    with patch("overnight.self_improver.ROOT", tmp_path), \
         patch("overnight.self_improver._get_repo_fingerprint", return_value="unique-test-fp"), \
         patch("overnight.self_improver.run_pytest", side_effect=mock_run_pytest), \
         patch("overnight.self_improver.is_ast_defeated", return_value=False), \
         patch("overnight.self_improver._generate_tdd_test", return_value=fake_test), \
         patch("overnight.self_improver.generate", return_value=None), \
         patch("overnight.self_improver._cleanup_tdd_artifact", side_effect=observing_cleanup):

        self_improver.apply_auto_fix(src, issue, api_keys={})

    test_file = tmp_path / "tests" / "test_tdd_auto_dummy_module.py"

    assert cleanup["called"], (
        "Centralized TDD cleanup must be invoked"
    )
    assert cleanup["path"] == test_file, (
        "Cleanup must receive the generated TDD artifact path"
    )
    assert cleanup["existed_before"], (
        "Artifact must exist when centralized cleanup begins"
    )
    assert not test_file.exists(), (
        "Ephemeral TDD artifact must be removed after apply_auto_fix returns"
    )


def test_tdd_artifact_cleaned_up_on_red_phase_exception(tdd_env):
    """A RED-phase exception must not leak the ephemeral TDD artifact."""
    tmp_path, src = tdd_env

    issue = {"category": "correctness", "description": "dummy bug"}
    fake_test = "def test_should_fail():\n    assert False\n"

    call_count = {"n": 0}

    def mock_run_pytest(targets, timeout=60):
        call_count["n"] += 1

        if call_count["n"] == 1:
            return "AssertionError: baseline failure"

        raise RuntimeError("simulated RED-phase pytest failure")

    from overnight import self_improver

    with patch("overnight.self_improver.ROOT", tmp_path), \
         patch("overnight.self_improver._get_repo_fingerprint", return_value="unique-test-fp"), \
         patch("overnight.self_improver.run_pytest", side_effect=mock_run_pytest), \
         patch("overnight.self_improver.is_ast_defeated", return_value=False), \
         patch("overnight.self_improver._generate_tdd_test", return_value=fake_test), \
         patch("overnight.self_improver.generate", return_value=None):

        self_improver.apply_auto_fix(src, issue, api_keys={})

    test_file = tmp_path / "tests" / "test_tdd_auto_dummy_module.py"

    assert not test_file.exists(), (
        "RED-phase exception must not leak an ephemeral TDD artifact"
    )
