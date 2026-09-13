"""Tests for engine/protected_kernel.py and its enforcement points."""
from pathlib import Path

import pytest

from engine.protected_kernel import (
    PROTECTED_PATHS,
    PROTECTED_PREFIXES,
    ProtectedKernelViolation,
    assert_not_protected,
    is_protected,
)
from engine.multi_file_patcher import (
    FilePatch,
    apply_multi_file_patches,
    validate_mutation_target,
)


# --- pure function tests ----------------------------------------------------

def test_is_protected_true_for_each_exact_path():
    for p in PROTECTED_PATHS:
        assert is_protected(p) is True


def test_is_protected_false_for_ordinary_path():
    assert is_protected("engine/advisory_identity.py") is False
    assert is_protected("tools/review_queue.py") is False


def test_is_protected_true_for_tests_prefix():
    assert is_protected("tests/test_anything.py") is True
    assert is_protected("tests/pipeline/test_x.py") is True


def test_is_protected_handles_dot_slash():
    assert is_protected("./overnight/self_improver.py") is True


def test_is_protected_handles_double_slash():
    assert is_protected("engine//protected_kernel.py") is True


def test_is_protected_accepts_path_objects():
    assert is_protected(Path("overnight/self_improver.py")) is True
    assert is_protected(Path("engine/advisory_identity.py")) is False


def test_assert_not_protected_raises_for_protected():
    with pytest.raises(ProtectedKernelViolation):
        assert_not_protected("overnight/self_improver.py")


def test_assert_not_protected_passes_for_unprotected():
    assert_not_protected("engine/advisory_identity.py")


def test_violation_is_value_error_subclass():
    assert issubclass(ProtectedKernelViolation, ValueError)


def test_protected_paths_non_empty():
    assert len(PROTECTED_PATHS) >= 10
    assert "tests/" in PROTECTED_PREFIXES


@pytest.mark.parametrize("path", [
    "overnight/self_improver.py",
    "engine/multi_file_patcher.py",
    "engine/protected_kernel.py",
    "engine/deterministic_policy.py",
    "engine/strict_queue_transitions.py",
    "engine/canonical_envelope.py",
    "engine/development_worker_gate.py",
    "engine/strict_quorum.py",
    "engine/trust_boundary.py",
    "contracts/worker_identity.py",
    "verify_p0.sh",
])
def test_expected_protected_path_present(path):
    assert path in PROTECTED_PATHS


# --- validate_mutation_target -----------------------------------------------

def _write(tmp_path: Path, rel: str, content: str = "x") -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_validate_mutation_target_rejects_protected_even_when_authorized(tmp_path):
    _write(tmp_path, "overnight/self_improver.py", "existing")
    with pytest.raises(ProtectedKernelViolation):
        validate_mutation_target(
            tmp_path,
            {"overnight/self_improver.py"},
            "overnight/self_improver.py",
        )


def test_validate_mutation_target_rejects_tests_even_when_authorized(tmp_path):
    _write(tmp_path, "tests/test_x.py", "existing")
    with pytest.raises(ProtectedKernelViolation):
        validate_mutation_target(
            tmp_path,
            {"tests/test_x.py"},
            "tests/test_x.py",
        )


def test_validate_mutation_target_accepts_authorized_non_protected(tmp_path):
    _write(tmp_path, "engine/advisory_identity.py", "existing")
    result = validate_mutation_target(
        tmp_path,
        {"engine/advisory_identity.py"},
        "engine/advisory_identity.py",
    )
    assert result.exists()


def test_validate_mutation_target_still_rejects_unauthorized(tmp_path):
    _write(tmp_path, "engine/advisory_identity.py", "existing")
    with pytest.raises(ValueError, match="not authorized"):
        validate_mutation_target(
            tmp_path,
            {"engine/something_else.py"},
            "engine/advisory_identity.py",
        )


# --- end-to-end through apply_multi_file_patches ----------------------------

def test_apply_multi_file_patches_refuses_protected_target(tmp_path):
    target = _write(tmp_path, "engine/multi_file_patcher.py", "old_content")
    patches = [
        FilePatch(
            file_path=target,
            search="old_content",
            replace="new_content",
        )
    ]
    with pytest.raises(ProtectedKernelViolation):
        apply_multi_file_patches(
            patches,
            repo_root=tmp_path,
            authorized_files={"engine/multi_file_patcher.py"},
        )


def test_apply_multi_file_patches_allows_non_protected_target(tmp_path):
    target = _write(tmp_path, "engine/advisory_identity.py", "old_content")
    patches = [
        FilePatch(
            file_path=target,
            search="old_content",
            replace="new_content",
        )
    ]
    result = apply_multi_file_patches(
        patches,
        repo_root=tmp_path,
        authorized_files={"engine/advisory_identity.py"},
    )
    assert target in result
    assert result[target] == "new_content"
