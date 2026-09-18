from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "propose_code.py"


def test_propose_code_help_is_read_only():
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Generate a bounded development proposal" in result.stdout
    assert "--auto" not in result.stdout


def test_propose_code_contains_no_git_mutation_primitives():
    source = RUNNER.read_text()

    forbidden = (
        '["git", "commit"',
        '["git", "add"',
        '["git", "reset"',
        '["git", "clean"',
        "git commit",
        "git add",
        "git reset",
        "git clean",
    )

    for token in forbidden:
        assert token not in source


def test_propose_code_contains_no_synthetic_quorum():
    source = RUNNER.read_text()

    forbidden = (
        "WorkerKeyRegistry",
        "judge_alpha",
        "judge_beta",
        "judge_gamma",
        "sign_vote",
        "evaluate_strict_proposal",
        "--auto",
        "local_operator",
        "AUTO-APPROVE",
        "AUTO-APPROV",
    )

    for token in forbidden:
        assert token not in source
