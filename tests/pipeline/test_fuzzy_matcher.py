import pytest
from engine.multi_file_patcher import FilePatch, apply_multi_file_patches


def _make(tmp_path, orig):
    f = tmp_path / "m.py"
    f.write_text(orig)
    return f


def test_exact_match_still_works(tmp_path):
    f = _make(tmp_path, "def foo():\n    return 1\n")

    patch = FilePatch(
        f,
        "def foo():\n    return 1\n",
        "def foo():\n    return 2\n",
    )

    result = apply_multi_file_patches([patch])

    assert "return 2" in result[f]


def test_indent_drift_is_rejected(tmp_path):
    f = _make(tmp_path, "def foo():\n    x = 1\n    return x\n")

    patch = FilePatch(
        f,
        "def foo():\n  x = 1\n  return x\n",
        "replacement",
    )

    with pytest.raises(ValueError, match="Exact patch match required"):
        apply_multi_file_patches([patch])


def test_blank_line_drift_is_rejected(tmp_path):
    f = _make(tmp_path, "def foo():\n    x = 1\n\n    return x\n")

    patch = FilePatch(
        f,
        "def foo():\n    x = 1\n    return x\n",
        "replacement",
    )

    with pytest.raises(ValueError, match="Exact patch match required"):
        apply_multi_file_patches([patch])
