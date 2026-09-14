"""
Local Aider development-worker adapter.

Aider is an implementation worker only:
- Receives an explicitly bounded file set.
- Runs only from a clean Git worktree.
- Must not create the authoritative Git commit.
- May stage files internally, but staging is never trusted.
- The adapter captures the complete HEAD -> working-tree delta.
- Any path outside the explicit allowlist is a hard rejection.
- Validation, quorum, safety gates, tests, canary, and Git governance
  remain outside this module.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import os
from pathlib import Path
from engine.aider_sandbox import build_aider_sandbox_command
from engine.development_budget_broker import DevelopmentBudgetBrokerContext
from engine.openrouter_catalog import validate_openrouter_model_allowed
from overnight.budget_manager import APIBudgetManager
import shutil
import subprocess
import uuid
from typing import Sequence

from engine.git_isolation import run_in_worktree


DEFAULT_OLLAMA_API_BASE = "http://127.0.0.1:11434"
DEFAULT_MODEL = "ollama_chat/qwen2.5-coder:3b"
DEFAULT_TIMEOUT = 300

AIDER_BUDGET_SHIM = Path(__file__).with_name("aider_budget_shim.py")


_PROVIDER_FAILURE_MARKERS = (
    "401",
    "403",
    "429",
    "authentication",
    "unauthorized",
    "forbidden",
    "rate limit",
    "rate-limit",
    "quota",
    "budget exhausted",
    "budget denied",
    "provider unavailable",
    "service unavailable",
    "connection",
    "connecterror",
    "connectionerror",
    "timed out",
    "timeout",
    "model not found",
    "does not exist",
    "api error",
    "api request",
    "cloud request blocked",
    "budget broker unavailable",
    "budget control failure",
    "no api key supplied",
)


def _provider_failure_observed(
    *,
    stdout: str,
    stderr: str,
) -> bool:
    """Detect provider/inference failures even when Aider exits 0."""

    text = f"{stdout}\n{stderr}".lower()
    return any(marker in text for marker in _PROVIDER_FAILURE_MARKERS)



def _as_text(value: str | bytes | None) -> str:
    """Normalize subprocess output to a string."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)

CLOUD_PROVIDER_BY_MODEL_PREFIX = {
    "openrouter/": "openrouter",
    "gemini/": "gemini",
}


def _provider_from_model(model: str) -> str | None:
    for prefix, provider in CLOUD_PROVIDER_BY_MODEL_PREFIX.items():
        if model.startswith(prefix):
            return provider
    return None


# Explicitly recognized Aider-only ephemeral artifacts.
# Anything else outside the orchestrator allowlist remains unauthorized.
AIDER_ARTIFACT_NAMES = frozenset({
    ".aider.chat.history.md",
    ".aider.input.history",
})
AIDER_ARTIFACT_DIRS = frozenset({
    ".aider.tags.cache.v4",
})


@dataclass(frozen=True)
class AiderWorkerResult:
    success: bool
    changed_files: tuple[str, ...]
    diff: str
    stdout: str
    stderr: str
    returncode: int
    reason: str

    model_name: str = ""
    prompt_hash: str = ""


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=True,
    )
    return Path(result.stdout.strip()).resolve()


def _resolve_bounded_files(
    repo_root: Path,
    files: Sequence[str | Path],
) -> list[Path]:
    if not files:
        raise ValueError("At least one bounded worker file is required.")

    resolved: list[Path] = []

    for item in files:
        candidate = (repo_root / item).resolve()

        try:
            candidate.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(
                f"Worker file escapes repository root: {item}"
            ) from exc

        if not candidate.is_file():
            raise FileNotFoundError(
                f"Worker file does not exist: {candidate}"
            )

        resolved.append(candidate)

    return list(dict.fromkeys(resolved))


def _is_aider_artifact(path: str) -> bool:
    """Return True only for explicitly recognized Aider ephemeral artifacts."""
    parts = Path(path).parts
    if path in AIDER_ARTIFACT_NAMES:
        return True
    return bool(parts and parts[0] in AIDER_ARTIFACT_DIRS)


def _worktree_paths_vs_head(repo_root: Path) -> tuple[str, ...]:
    """Return every source path changed from the worker baseline.

    Known Aider-only ephemeral artifacts are deliberately excluded.
    """
    tracked = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    paths = set()

    for line in tracked.stdout.splitlines():
        line = line.strip()
        if line and not _is_aider_artifact(line):
            paths.add(line)

    for line in untracked.stdout.splitlines():
        line = line.strip()
        if line and not _is_aider_artifact(line):
            paths.add(line)

    return tuple(sorted(paths))


def _cleanup_aider_artifacts(repo_root: Path) -> None:
    """Remove only known ephemeral Aider artifacts."""
    for name in AIDER_ARTIFACT_NAMES:
        target = repo_root / name
        try:
            if target.is_file() or target.is_symlink():
                target.unlink()
        except OSError:
            pass

    for name in AIDER_ARTIFACT_DIRS:
        target = repo_root / name
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
        except OSError:
            pass


def _is_clean_worktree(repo_root: Path) -> bool:
    """Require both tracked and untracked state to be clean."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and not result.stdout.strip()


def _diff_vs_head(
    repo_root: Path,
    paths: Sequence[str],
    *,
    base_ref: str = "HEAD",
) -> str:
    """Return reviewable diffs for tracked and untracked paths."""
    chunks: list[str] = []

    for path in sorted(paths):
        absolute = repo_root / path

        tracked_check = subprocess.run(
            [
                "git",
                "ls-files",
                "--error-unmatch",
                "--",
                path,
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )

        if tracked_check.returncode == 0:
            result = subprocess.run(
                [
                    "git",
                    "diff",
                    base_ref,
                    "--",
                    path,
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"git diff failed for tracked path {path}: "
                    f"{result.stderr.strip()}"
                )

            if result.stdout:
                chunks.append(result.stdout)

            continue

        if not absolute.exists():
            continue

        result = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--",
                "/dev/null",
                str(absolute),
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode not in (0, 1):
            raise RuntimeError(
                f"git diff --no-index failed for untracked path {path}: "
                f"{result.stderr.strip()}"
            )

        if result.stdout:
            chunks.append(result.stdout)

    return "".join(chunks)


def run_aider_worker(
    prompt: str,
    files: Sequence[str | Path],
    *,
    model: str = DEFAULT_MODEL,
    api_base: str = DEFAULT_OLLAMA_API_BASE,
    timeout: int = DEFAULT_TIMEOUT,
    provider_name: str | None = None,
    api_key_env: str | None = None,
) -> AiderWorkerResult:
    """Run Aider as a bounded, non-committing implementation worker."""

    if not prompt or not prompt.strip():
        return AiderWorkerResult(
            success=False,
            changed_files=(),
            diff="",
            stdout="",
            stderr="",
            returncode=-1,
            reason="Worker prompt is empty.",
        )

    if timeout <= 0:
        return AiderWorkerResult(
            success=False,
            changed_files=(),
            diff="",
            stdout="",
            stderr="",
            returncode=-1,
            reason="Worker timeout must be positive.",
        )

    repo_root = _repo_root()

    # Safety invariant: the canonical developer checkout must start clean.
    # Aider itself never receives the canonical checkout as its cwd.
    if not _is_clean_worktree(repo_root):
        return AiderWorkerResult(
            success=False,
            changed_files=(),
            diff="",
            stdout="",
            stderr="",
            returncode=-1,
            reason="Worker repository must start from a clean worktree.",
        )

    bounded_files = _resolve_bounded_files(repo_root, files)
    allowed = {
        str(path.relative_to(repo_root))
        for path in bounded_files
    }

    aider = shutil.which("aider")
    if not aider:
        return AiderWorkerResult(
            success=False,
            changed_files=(),
            diff="",
            stdout="",
            stderr="",
            returncode=127,
            reason="Aider executable not found on PATH.",
        )

    relative_files = sorted(allowed)

    selected_provider = provider_name or _provider_from_model(model)

    if selected_provider == "openrouter":
        if not validate_openrouter_model_allowed(
            model,
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        ):
            return AiderWorkerResult(
                success=False,
                changed_files=(),
                diff="",
                stdout="",
                stderr="",
                returncode=126,
                reason="OpenRouter model rejected by free-only development policy.",
                model_name=model,
            )

    api_key = None
    if api_key_env:
        api_key = os.environ.get(api_key_env, "").strip()
        if not api_key:
            return AiderWorkerResult(
                success=False,
                changed_files=(),
                diff="",
                stdout="",
                stderr="",
                returncode=126,
                reason=(
                    "Required development credential is missing: "
                    + api_key_env
                ),
                model_name=model,
            )

    if selected_provider is not None and not api_key_env:
        raise RuntimeError(
            "Cloud Aider worker attempts require an explicit api_key_env."
        )

    budget_context = (
        DevelopmentBudgetBrokerContext(
            APIBudgetManager(),
            allowed_provider=selected_provider,
            allowed_model=model,
        )
        if selected_provider is not None
        else nullcontext(None)
    )

    env = os.environ.copy()
    env["OLLAMA_API_BASE"] = api_base

    # Aider command is constructed only after entering the disposable worker worktree.
    branch_name = f"isolated/aider-{uuid.uuid4().hex[:8]}"

    try:
        with run_in_worktree(
            repo_root,
            branch_name,
            base_ref="HEAD",
        ) as worker_root:

            head_before = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worker_root,
                text=True,
                capture_output=True,
                check=False,
            )

            if head_before.returncode != 0:
                return AiderWorkerResult(
                    success=False,
                    changed_files=(),
                    diff="",
                    stdout="",
                    stderr=head_before.stderr,
                    returncode=125,
                    reason="Failed closed: could not establish worker HEAD.",
                    model_name=model,
                )

            base_head = head_before.stdout.strip()

            with budget_context as budget_broker:
                command = build_aider_sandbox_command(
                    aider_executable=aider,
                    worker_root=worker_root,
                    model=model,
                    prompt=prompt,
                    relative_files=relative_files,
                    api_base=api_base,
                    api_key_env=api_key_env,
                    api_key=api_key,
                    budget_socket_path=(
                        budget_broker.socket_path
                        if budget_broker is not None
                        else None
                    ),
                    budget_shim_path=(
                        AIDER_BUDGET_SHIM
                        if budget_broker is not None
                        else None
                    ),
                )

                try:
                    completed = subprocess.run(
                        command,
                        cwd=worker_root,
                        env=env,
                        text=True,
                        capture_output=True,
                        timeout=timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    changed = _worktree_paths_vs_head(worker_root)
                    _cleanup_aider_artifacts(worker_root)
                    return AiderWorkerResult(
                        success=False,
                        changed_files=changed,
                        diff="",
                        stdout=_as_text(exc.stdout),
                        stderr=_as_text(exc.stderr),
                        returncode=124,
                        reason=f"Aider worker timed out after {timeout}s.",
                        model_name=model,
                    )
                except OSError as exc:
                    return AiderWorkerResult(
                        success=False,
                        changed_files=(),
                        diff="",
                        stdout="",
                        stderr=str(exc),
                        returncode=126,
                        reason=f"Failed to launch Aider: {exc}",
                        model_name=model,
                    )


            head_after = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worker_root,
                text=True,
                capture_output=True,
                check=False,
            )

            if head_after.returncode != 0:
                return AiderWorkerResult(
                    success=False,
                    changed_files=(),
                    diff="",
                    stdout=completed.stdout,
                    stderr=(
                        completed.stderr
                        + "\n"
                        + head_after.stderr
                    ),
                    returncode=125,
                    reason=(
                        "Aider isolation failed closed: "
                        "could not verify worker HEAD."
                    ),
                    model_name=model,
                )

            if head_after.stdout.strip() != base_head:
                changed_after_commit = _worktree_paths_vs_head(
                    worker_root
                )

                diff = _diff_vs_head(
                    worker_root,
                    list(changed_after_commit),
                    base_ref=base_head,
                )

                _cleanup_aider_artifacts(worker_root)

                return AiderWorkerResult(
                    success=False,
                    changed_files=changed_after_commit,
                    diff=diff,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    returncode=125,
                    reason=(
                        "Aider modified Git history; worker commits "
                        "are forbidden."
                    ),
                    model_name=model,
                )

            changed = _worktree_paths_vs_head(worker_root)

            unauthorized = tuple(
                path for path in changed
                if path not in allowed
            )

            if unauthorized:
                diff = _diff_vs_head(worker_root, list(changed), base_ref=base_head)
                _cleanup_aider_artifacts(worker_root)
                return AiderWorkerResult(
                    success=False,
                    changed_files=changed,
                    diff=diff,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    returncode=completed.returncode,
                    reason=(
                        "Aider modified unauthorized paths: "
                        + ", ".join(unauthorized)
                    ),
                    model_name=model,
                )

            if completed.returncode != 0:
                diff = _diff_vs_head(worker_root, list(changed), base_ref=base_head)
                _cleanup_aider_artifacts(worker_root)
                return AiderWorkerResult(
                    success=False,
                    changed_files=changed,
                    diff=diff,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    returncode=completed.returncode,
                    reason="Aider exited with a non-zero status.",
                    model_name=model,
                )

            if not changed:
                completed_stdout = _as_text(completed.stdout)
                completed_stderr = _as_text(completed.stderr)

                if _provider_failure_observed(
                    stdout=completed_stdout,
                    stderr=completed_stderr,
                ):
                    _cleanup_aider_artifacts(worker_root)
                    return AiderWorkerResult(
                        success=False,
                        changed_files=(),
                        diff="",
                        stdout=completed_stdout,
                        stderr=completed_stderr,
                        returncode=completed.returncode,
                        reason=(
                            "Aider provider/inference failure observed "
                            "without a working-tree change."
                        ),
                        model_name=model,
                    )

                _cleanup_aider_artifacts(worker_root)
                return AiderWorkerResult(
                    success=False,
                    changed_files=(),
                    diff="",
                    stdout=completed_stdout,
                    stderr=completed_stderr,
                    returncode=completed.returncode,
                    reason="Aider completed but produced no working-tree change.",
                    model_name=model,
                )

            diff = _diff_vs_head(worker_root, list(changed), base_ref=base_head)

            if not diff.strip():
                _cleanup_aider_artifacts(worker_root)
                return AiderWorkerResult(
                    success=False,
                    changed_files=changed,
                    diff="",
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    returncode=completed.returncode,
                    reason="Changed paths detected but no diff was produced.",
                    model_name=model,
                )

            _cleanup_aider_artifacts(worker_root)

            return AiderWorkerResult(
                success=True,
                changed_files=changed,
                diff=diff,
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
                reason="Aider produced an allowlisted working-tree proposal in isolation.",
                model_name=model,
            )

    except Exception as exc:
        return AiderWorkerResult(
            success=False,
            changed_files=(),
            diff="",
            stdout="",
            stderr=str(exc),
            returncode=125,
            reason=f"Aider isolation failed closed: {exc}",
            model_name=model,
        )
