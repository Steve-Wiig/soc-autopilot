from __future__ import annotations

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
