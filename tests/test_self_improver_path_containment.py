from __future__ import annotations

from types import SimpleNamespace

import pytest

import overnight.self_improver as self_improver
from overnight.self_improver import _resolve_contained_repository_path


@pytest.fixture
def repo_root(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "valid.py").write_text("valid\n")

    monkeypatch.setattr(self_improver, "ROOT", root)

    return root.resolve()


@pytest.mark.parametrize(
    "bad_path",
    [
        "../../../etc/passwd",
        "../../../../etc/passwd",
        "/etc/passwd",
        "/root/.ssh/authorized_keys",
    ],
)
def test_rejects_path_outside_root(repo_root, bad_path):
    with pytest.raises(ValueError, match="escapes repository root"):
        _resolve_contained_repository_path(bad_path)


def test_rejects_symlink_escape(repo_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    target = outside / "secret.txt"
    target.write_text("secret\n")

    link = repo_root / "symlink.txt"

    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unsupported in this environment: {exc}")

    with pytest.raises(ValueError, match="escapes repository root"):
        _resolve_contained_repository_path("symlink.txt")


def test_accepts_valid_repository_path(repo_root):
    resolved = _resolve_contained_repository_path("sub/valid.py")

    assert resolved == (repo_root / "sub" / "valid.py").resolve()


def test_aider_mode_is_opt_in(monkeypatch):
    monkeypatch.delenv("SOC_AUTOPILOT_DEVELOPMENT_WORKER", raising=False)
    assert self_improver._aider_mode_enabled() is False

    monkeypatch.setenv("SOC_AUTOPILOT_DEVELOPMENT_WORKER", "legacy")
    assert self_improver._aider_mode_enabled() is False

    monkeypatch.setenv("SOC_AUTOPILOT_DEVELOPMENT_WORKER", "aider")
    assert self_improver._aider_mode_enabled() is True


def test_aider_candidate_is_materialized_through_existing_patch_format(
    repo_root,
    monkeypatch,
):
    target = repo_root / "sub" / "valid.py"
    original = target.read_text()

    worker_result = SimpleNamespace(
        success=True,
        changed_files=("sub/valid.py",),
        diff=(
            "diff --git a/sub/valid.py b/sub/valid.py\n"
            "--- a/sub/valid.py\n"
            "+++ b/sub/valid.py\n"
            "@@ -1 +1,2 @@\n"
            " valid\n"
            "+changed\n"
        ),
    )

    dispatch_result = SimpleNamespace(
        accepted_for_review=True,
        worker_result=worker_result,
        reason="Aider produced a proposal.",
    )

    monkeypatch.setattr(
        self_improver,
        "dispatch_development_worker",
        lambda request: dispatch_result,
    )

    raw = self_improver._generate_aider_candidate_patch(
        file_path=target,
        issue={"description": "append a harmless test marker"},
        original=original,
        tdd_block="",
        forensic_context="",
        failed_attempt_1_raw="",
        pre_flight_rejection_msg="",
    )

    assert "<<<<<<< sub/valid.py" in raw
    assert "changed\n" in raw
    assert ">>>>>>> REPLACE" in raw

    # The canonical test repository must remain untouched.
    assert target.read_text() == original


def test_aider_rejects_unauthorized_changed_path(repo_root, monkeypatch):
    target = repo_root / "sub" / "valid.py"

    worker_result = SimpleNamespace(
        success=True,
        changed_files=("sub/valid.py", "evil.py"),
        diff="not-used",
    )

    dispatch_result = SimpleNamespace(
        accepted_for_review=True,
        worker_result=worker_result,
        reason="Aider produced a proposal.",
    )

    monkeypatch.setattr(
        self_improver,
        "dispatch_development_worker",
        lambda request: dispatch_result,
    )

    with pytest.raises(RuntimeError, match="unauthorized files"):
        self_improver._generate_aider_candidate_patch(
            file_path=target,
            issue={"description": "test"},
            original=target.read_text(),
            tdd_block="",
            forensic_context="",
            failed_attempt_1_raw="",
            pre_flight_rejection_msg="",
        )


def test_aider_rejects_empty_diff(repo_root, monkeypatch):
    target = repo_root / "sub" / "valid.py"

    worker_result = SimpleNamespace(
        success=True,
        changed_files=("sub/valid.py",),
        diff="",
    )

    dispatch_result = SimpleNamespace(
        accepted_for_review=True,
        worker_result=worker_result,
        reason="Aider produced a proposal.",
    )

    monkeypatch.setattr(
        self_improver,
        "dispatch_development_worker",
        lambda request: dispatch_result,
    )

    with pytest.raises(ValueError, match="empty diff"):
        self_improver._generate_aider_candidate_patch(
            file_path=target,
            issue={"description": "test"},
            original=target.read_text(),
            tdd_block="",
            forensic_context="",
            failed_attempt_1_raw="",
            pre_flight_rejection_msg="",
        )


def test_aider_rejects_invalid_git_diff(repo_root):
    target = repo_root / "sub" / "valid.py"

    with pytest.raises(
        ValueError,
        match="failed deterministic patch validation",
    ):
        self_improver._materialize_aider_diff_as_search_replace(
            "this is not a git diff",
            file_path=target,
            original=target.read_text(),
        )


def test_legacy_mode_does_not_select_aider(monkeypatch):
    monkeypatch.setenv("SOC_AUTOPILOT_DEVELOPMENT_WORKER", "legacy")

    calls = []

    def fake_dispatch(request):
        calls.append(request)
        raise AssertionError("Aider dispatcher must not be selected in legacy mode.")

    monkeypatch.setattr(
        self_improver,
        "dispatch_development_worker",
        fake_dispatch,
    )

    assert self_improver._aider_mode_enabled() is False
    assert calls == []
