from pathlib import Path
import pytest
from engine.multi_file_patcher import FilePatch, apply_multi_file_patches


def _make(tmp_path, orig):
    f = tmp_path / "m.py"
    f.write_text(orig)
    return f


def _authorize(tmp_path, f):
    return {f.relative_to(tmp_path)}


def test_exact_match_still_works(tmp_path):
    f = _make(tmp_path, "def foo():\n    return 1\n")

    patch = FilePatch(
        f,
        "def foo():\n    return 1\n",
        "def foo():\n    return 2\n",
    )

    result = apply_multi_file_patches(
        [patch],
        repo_root=tmp_path,
        authorized_files=_authorize(tmp_path, f),
    )

    assert "return 2" in result[f]


def test_indent_drift_is_rejected(tmp_path):
    f = _make(tmp_path, "def foo():\n    x = 1\n    return x\n")

    patch = FilePatch(
        f,
        "def foo():\n  x = 1\n  return x\n",
        "replacement",
    )

    with pytest.raises(ValueError, match="Exact patch match required"):
        apply_multi_file_patches(
            [patch],
            repo_root=tmp_path,
            authorized_files=_authorize(tmp_path, f),
        )


def test_blank_line_drift_is_rejected(tmp_path):
    f = _make(tmp_path, "def foo():\n    x = 1\n\n    return x\n")

    patch = FilePatch(
        f,
        "def foo():\n    x = 1\n    return x\n",
        "replacement",
    )

    with pytest.raises(ValueError, match="Exact patch match required"):
        apply_multi_file_patches(
            [patch],
            repo_root=tmp_path,
            authorized_files=_authorize(tmp_path, f),
        )


def test_unauthorized_path_rejected(tmp_path):
    """P0-2: patching a file not in authorized_files must raise."""
    f = _make(tmp_path, "def foo():\n    return 1\n")

    patch = FilePatch(
        f,
        "def foo():\n    return 1\n",
        "def foo():\n    return 2\n",
    )

    with pytest.raises(ValueError, match="not authorized"):
        apply_multi_file_patches(
            [patch],
            repo_root=tmp_path,
            authorized_files=set(),
        )


def test_path_outside_repo_rejected(tmp_path):
    """P0-2: a patch targeting a file outside the repo root must raise."""
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def foo():\n    return 1\n")

    patch = FilePatch(
        outside,
        "def foo():\n    return 1\n",
        "def foo():\n    return 2\n",
    )

    with pytest.raises(ValueError, match="outside repository root"):
        apply_multi_file_patches(
            [patch],
            repo_root=repo,
            authorized_files={Path("outside.py")},
        )
