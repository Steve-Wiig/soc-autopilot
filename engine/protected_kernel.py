"""
Protected kernel: files the autonomous self-improvement path must not mutate.

The self-improvement loop generates, validates, and applies patches to the
codebase. Without this gate, it could weaken its own safety controls:
modify the routing policy, remove gates in the verifier, alter the
deterministic authorization boundary, or weaken the tests that pin the
invariants.

The set below is a literal constant in code. It is not configurable at
runtime. Modifying it requires a human commit, which is exactly the gate
we want.

Enforcement points:
  * engine.multi_file_patcher.validate_mutation_target -- authoritative
  * overnight.self_improver.apply_auto_fix -- fast-path refusal before
    burning tokens on TDD generation, forensic analysis, or cloud calls

Any patch that targets a protected path is refused. The caller escalates
to manual review rather than retrying.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union


class ProtectedKernelViolation(ValueError):
    """Raised when a patch targets a protected kernel path.

    Subclasses ValueError so existing except ValueError handlers still
    catch it. Callers that want to distinguish it can do so explicitly.
    """


PROTECTED_PATHS: frozenset[str] = frozenset({
    # The self-improvement loop and its safety gates.
    "overnight/self_improver.py",
    "overnight/safety_gates.py",

    # Patch application path. The patcher protects itself so a patch
    # cannot remove the protected-kernel check.
    "engine/multi_file_patcher.py",
    "engine/protected_kernel.py",

    # Deterministic control plane.
    "engine/strict_queue_transitions.py",
    "engine/canonical_envelope.py",
    "engine/deterministic_policy.py",
    "engine/development_worker_gate.py",
    "engine/strict_quorum.py",
    "engine/trust_boundary.py",

    # Cryptographic identity contract.
    "contracts/worker_identity.py",

    # The tree-wide verifier.
    "verify_p0.sh",
    "engine/aider_development_worker.py",
    "engine/aider_budget_shim.py",
    "engine/development_budget_broker.py",
    "engine/development_worker_dispatch.py",
    "engine/development_worker_pipeline.py",
    "engine/development_candidate.py",
    "engine/git_isolation.py",
    "engine/isolated_worker_runner.py",
})


PROTECTED_PREFIXES: tuple[str, ...] = (
    # Test files pin the invariants. If the pipeline can modify them,
    # it can modify the assertions.
    "tests/",
)


def _normalise(rel_path: Union[str, Path]) -> str:
    s = str(rel_path).replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    while "//" in s:
        s = s.replace("//", "/")
    return s


def is_protected(rel_path: Union[str, Path]) -> bool:
    """Return True if a repository-relative path is in the protected set."""
    s = _normalise(rel_path)
    if s in PROTECTED_PATHS:
        return True
    for prefix in PROTECTED_PREFIXES:
        if s.startswith(prefix):
            return True
    return False


def assert_not_protected(rel_path: Union[str, Path]) -> None:
    """Raise ProtectedKernelViolation if the path is protected."""
    if is_protected(rel_path):
        raise ProtectedKernelViolation(
            f"Path is in the protected kernel and cannot be mutated by "
            f"the autonomous path: {rel_path}"
        )
