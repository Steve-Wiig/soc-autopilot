"""
Regression tests for the tdd_kept_path / tdd_write_path split in apply_auto_fix().

Bug: a cleanup patch made tdd_kept_path truthy even for a vacuous
(non-failing) generated TDD test, which bypassed the no-regression-test
safety gate and weakened red/green acceptance.
"""
from unittest.mock import patch, MagicMock

import pytest

from overnight import self_improver as si


def _fake_issue(**overrides):
    issue = {
        "description": "minor maintainability nit",
        "category": "maintainability",
        "severity": "low",
        "effort": "small",
        "impact": "low",
    }
    issue.update(overrides)
    return issue


def _tdd_path_for(file_path):
    return si.ROOT / "tests" / f"test_tdd_auto_{file_path.stem}.py"


@pytest.fixture
def target_file(tmp_path, monkeypatch):
    fake_root = tmp_path
    (fake_root / "tests").mkdir()
    (fake_root / "overnight").mkdir()
    src = fake_root / "engine" / "widget.py"
    src.parent.mkdir()
    src.write_text("def widget():\n    return 1\n")
    monkeypatch.setattr(si, "ROOT", fake_root)
    monkeypatch.setattr(
        si,
        "FIX_BACKLOG",
        fake_root / "overnight" / "fix_backlog.json",
    )
    return src


def test_vacuous_test_does_not_satisfy_acceptance(target_file):
    tdd_path = _tdd_path_for(target_file)

    with patch.object(si, "is_ast_defeated", return_value=False), \
         patch("subprocess.check_output", return_value="main\n"), \
         patch.object(
             si,
             "_generate_tdd_test",
             return_value="def test_x():\n    assert True\n",
         ), \
         patch.object(si, "run_pytest_cached", return_value=None), \
         patch.object(si, "run_pytest", return_value=None), \
         patch.object(si, "_forensic_analysis", return_value=""), \
         patch.object(si, "_get_imported_signatures", return_value=""), \
         patch.object(si, "_retrieve_similar_fixes", return_value=""), \
         patch.object(si, "_retrieve_failed_patterns", return_value=""), \
         patch.object(
             si,
             "generate",
             return_value=(
                 "<<<<<<< engine/widget.py\n"
                 "def widget():\n"
                 "    return 1\n"
                 "=======\n"
                 "def widget():\n"
                 "    return 2\n"
                 ">>>>>>> REPLACE"
             ),
         ), \
         patch(
             "overnight.safety_gates.pre_flight_safety_check",
             return_value=(True, ""),
         ), \
         patch.object(si, "parse_multi_file_diff", return_value={"fake": "patch"}), \
         patch.object(
             si,
             "apply_multi_file_patches",
             return_value={
                 target_file: "def widget():\n    return 2\n"
             },
         ), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         patch.object(si, "_store_proven_fix"), \
         patch.object(si, "_record_ledger") as mock_ledger, \
         patch("tools.shadow_canary.run_canary") as mock_canary:

        issue = _fake_issue()
        issue["category"] = "correctness"  # Enforce strict TDD path (bypass low-risk exemption)
        result = si.apply_auto_fix(target_file, issue, {})

    assert result is False
    mock_canary.assert_not_called()
    assert not tdd_path.exists()

    ledger_calls = [c.args for c in mock_ledger.call_args_list]
    assert any(
        call[2] == "STALE" and "regression test" in call[3]
        for call in ledger_calls
    ), f"Expected STALE/no-regression-test entry, got: {ledger_calls}"


def test_valid_red_test_still_gates_acceptance(target_file):
    tdd_path = _tdd_path_for(target_file)
    original = target_file.read_text()

    pytest_sequence = [
        "still red on generation",  # TDD red phase
        None,                       # sniper pytest: no new failures
        "TDD still failing",        # TDD acceptance: still red
        "TDD still failing",        # defensive: any retry remains red
        "TDD still failing",
    ]

    with patch.object(si, "is_ast_defeated", return_value=False), \
         patch("subprocess.check_output", return_value="main\n"), \
         patch.object(
             si,
             "_generate_tdd_test",
             return_value="def test_x():\n    assert False\n",
         ), \
         patch.object(si, "run_pytest_cached", return_value="boom"), \
         patch.object(si, "run_pytest", side_effect=pytest_sequence), \
         patch.object(si, "_forensic_analysis", return_value=""), \
         patch.object(si, "_get_imported_signatures", return_value=""), \
         patch.object(si, "_retrieve_similar_fixes", return_value=""), \
         patch.object(si, "_retrieve_failed_patterns", return_value=""), \
         patch(
             "overnight.safety_gates.pre_flight_safety_check",
             return_value=(True, ""),
         ), \
         patch.object(
             si,
             "generate",
             return_value=(
                 "<<<<<<< engine/widget.py\n"
                 "    return 1\n"
                 "=======\n"
                 "    return 1  # no-op\n"
                 ">>>>>>> REPLACE"
             ),
         ), \
         patch.object(si, "parse_multi_file_diff", return_value={"fake": "patch"}), \
         patch.object(
             si,
             "apply_multi_file_patches",
             return_value={
                 target_file: "def widget():\n    return 1  # no-op\n"
             },
         ), \
         patch.object(si, "perform_autopsy", return_value="unhelpful patch"), \
         patch.object(si, "_store_failed_fix"), \
         patch.object(si, "check_and_record_defeat"), \
         patch.object(si, "_record_ledger"), \
         patch("tools.shadow_canary.run_canary") as mock_canary:

        issue = _fake_issue()
        issue["category"] = "correctness"  # Enforce strict TDD path (bypass low-risk exemption)
        result = si.apply_auto_fix(target_file, issue, {})

    assert result is False
    mock_canary.assert_not_called()
    assert not tdd_path.exists()
    assert target_file.read_text() == original


def test_valid_red_test_allows_success_when_it_actually_passes(target_file):
    tdd_path = _tdd_path_for(target_file)

    pytest_sequence = [
        "still red on generation",
        None,
        None,
    ]

    with patch.object(si, "is_ast_defeated", return_value=False), \
         patch("subprocess.check_output", return_value="main\n"), \
         patch.object(
             si,
             "_generate_tdd_test",
             return_value="def test_x():\n    assert False\n",
         ), \
         patch.object(si, "run_pytest_cached", return_value="boom"), \
         patch.object(si, "run_pytest", side_effect=pytest_sequence), \
         patch.object(si, "_forensic_analysis", return_value=""), \
         patch.object(si, "_get_imported_signatures", return_value=""), \
         patch.object(si, "_retrieve_similar_fixes", return_value=""), \
         patch.object(si, "_retrieve_failed_patterns", return_value=""), \
         patch(
             "overnight.safety_gates.pre_flight_safety_check",
             return_value=(True, ""),
         ), \
         patch.object(
             si,
             "generate",
             return_value=(
                 "<<<<<<< engine/widget.py\n"
                 "    return 1\n"
                 "=======\n"
                 "    return 2\n"
                 ">>>>>>> REPLACE"
             ),
         ), \
         patch.object(si, "parse_multi_file_diff", return_value={"fake": "patch"}), \
         patch.object(
             si,
             "apply_multi_file_patches",
             return_value={
                 target_file: "def widget():\n    return 2\n"
             },
         ), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         patch("tools.shadow_canary.run_canary", return_value=True), \
         patch.object(si, "_store_proven_fix"), \
         patch.object(si, "_record_ledger"):

        issue = _fake_issue()
        issue["category"] = "correctness"  # Enforce strict TDD path (bypass low-risk exemption)
        result = si.apply_auto_fix(target_file, issue, {})

    assert result is True
    assert not tdd_path.exists()
    assert target_file.read_text() == "def widget():\n    return 2\n"


def test_cleanup_still_happens_for_vacuous_test(target_file):
    tdd_path = _tdd_path_for(target_file)

    with patch.object(si, "is_ast_defeated", return_value=False), \
         patch("subprocess.check_output", return_value="main\n"), \
         patch.object(
             si,
             "_generate_tdd_test",
             return_value="def test_x():\n    assert True\n",
         ), \
         patch.object(si, "run_pytest_cached", return_value=None), \
         patch.object(si, "run_pytest", return_value=None), \
         patch.object(si, "_record_ledger"):

        si.apply_auto_fix(target_file, _fake_issue(), {})

    assert not tdd_path.exists()


def test_exception_during_red_check_leaves_no_orphan(target_file):
    tdd_path = _tdd_path_for(target_file)

    with patch.object(si, "is_ast_defeated", return_value=False), \
         patch("subprocess.check_output", return_value="main\n"), \
         patch.object(
             si,
             "_generate_tdd_test",
             return_value="def test_x():\n    assert True\n",
         ), \
         patch.object(si, "run_pytest_cached", return_value=None), \
         patch.object(
             si,
             "run_pytest",
             side_effect=RuntimeError("pytest exploded"),
         ), \
         patch.object(si, "_record_ledger"):

        issue = _fake_issue()
        issue["category"] = "correctness"  # Enforce strict TDD path (bypass low-risk exemption)
        result = si.apply_auto_fix(target_file, issue, {})

    assert result is False
    assert not tdd_path.exists()
