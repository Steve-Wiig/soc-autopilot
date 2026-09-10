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

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Sequence


DEFAULT_OLLAMA_API_BASE = "http://127.0.0.1:11435"
DEFAULT_MODEL = "ollama_chat/qwen2.5-coder:3b"
DEFAULT_TIMEOUT = 180

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
) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD", "--", *paths],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout


def run_aider_worker(
    prompt: str,
    files: Sequence[str | Path],
    *,
    model: str = DEFAULT_MODEL,
    api_base: str = DEFAULT_OLLAMA_API_BASE,
    timeout: int = DEFAULT_TIMEOUT,
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

    # Safety invariant: don't risk destroying or conflating pre-existing
    # developer changes with worker output.
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

    env = os.environ.copy()
    env["OLLAMA_API_BASE"] = api_base

    command = [
        aider,
        "--model",
        model,
        "--message",
        prompt,
        "--no-show-model-warnings",
        "--yes-always",
        "--no-auto-commits",
        "--no-gitignore",
        "--map-tokens",
        "0",
        "--no-analytics",
        *relative_files,
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        changed = _worktree_paths_vs_head(repo_root)
        _cleanup_aider_artifacts(repo_root)
        return AiderWorkerResult(
            success=False,
            changed_files=changed,
            diff="",
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            returncode=124,
            reason=f"Aider worker timed out after {timeout}s.",
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
        )

    changed = _worktree_paths_vs_head(repo_root)
    unauthorized = tuple(
        path for path in changed
        if path not in allowed
    )

    if unauthorized:
        diff = _diff_vs_head(repo_root, list(changed))
        _cleanup_aider_artifacts(repo_root)
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
        )

    if completed.returncode != 0:
        diff = _diff_vs_head(repo_root, list(changed))
        _cleanup_aider_artifacts(repo_root)
        return AiderWorkerResult(
            success=False,
            changed_files=changed,
            diff=diff,
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            reason="Aider exited with a non-zero status.",
        )

    if not changed:
        _cleanup_aider_artifacts(repo_root)
        return AiderWorkerResult(
            success=False,
            changed_files=(),
            diff="",
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            reason="Aider completed but produced no working-tree change.",
        )

    diff = _diff_vs_head(repo_root, list(changed))

    if not diff.strip():
        _cleanup_aider_artifacts(repo_root)
        return AiderWorkerResult(
            success=False,
            changed_files=changed,
            diff="",
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            reason="Changed paths detected but no diff was produced.",
        )

    _cleanup_aider_artifacts(repo_root)

    return AiderWorkerResult(
        success=True,
        changed_files=changed,
        diff=diff,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        reason="Aider produced an allowlisted working-tree proposal.",
    )
