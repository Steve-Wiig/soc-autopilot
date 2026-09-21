"""Filesystem-sandboxed launcher for the bounded Aider development worker.

Security invariant:
    Aider receives the disposable worker worktree as /workspace.
    The authoritative checkout is never mounted into the namespace.

Git is deliberately disabled inside Aider. The parent worker owns all
Git inspection and proposal validation.
"""

from __future__ import annotations

from pathlib import Path
import os
import shutil
from typing import Sequence

# Mount points / paths inside the bwrap namespace. Named here so the
# command-assembly code and any future callers refer to a single source
# of truth instead of repeating string literals.
_SANDBOX_WORKSPACE_PATH = "/workspace"
_SANDBOX_CONTROL_PATH = "/aider-control"
_SANDBOX_BUDGET_PATH = "/aider-budget"
_SANDBOX_HOME_SUBDIR = "sandbox-home"


def _require_bwrap_executable() -> str:
    """Locate the bwrap executable on PATH.

    Raises:
        RuntimeError: If bubblewrap is not installed. Aider must never
            run unsandboxed.
    """
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError(
            "Aider sandbox requires bubblewrap (bwrap); "
            "refusing unsandboxed execution."
        )
    return bwrap


def _validate_worker_root(worker_root: Path) -> Path:
    """Resolve and validate the disposable worker worktree directory.

    Raises:
        RuntimeError: If the worker root does not exist as a directory.
    """
    resolved = Path(worker_root).resolve()

    if not resolved.is_dir():
        raise RuntimeError(
            f"Aider sandbox worker root does not exist: {resolved}"
        )

    return resolved


def _validate_aider_executable(aider_executable: str) -> Path:
    """Resolve and validate the Aider launcher executable path.

    Raises:
        RuntimeError: If the executable does not exist.
    """
    resolved = Path(aider_executable).resolve()

    if not resolved.is_file():
        raise RuntimeError(
            f"Aider executable does not exist: {resolved}"
        )

    return resolved


def _validate_credential(api_key_env: str | None, api_key: str | None) -> None:
    """Ensure a required development credential was actually supplied.

    Raises:
        RuntimeError: If an environment variable name was specified for
            the credential but no value was provided.
    """
    if api_key_env and not api_key:
        raise RuntimeError(
            f"Required development credential is missing: {api_key_env}"
        )


def _validate_budget_wiring(
    budget_socket_path: Path | None,
    budget_shim_path: Path | None,
) -> tuple[Path | None, Path | None]:
    """Validate the optional budget-broker socket and trusted shim pairing.

    Both must be supplied together, or neither.

    Raises:
        RuntimeError: If only one of the pair is supplied, or if the
            supplied paths do not exist.
    """
    if (budget_socket_path is None) != (budget_shim_path is None):
        raise RuntimeError(
            "Budget socket and budget shim must be supplied together."
        )

    if budget_socket_path is None:
        return None, None

    resolved_socket_path = Path(budget_socket_path).resolve()
    resolved_shim_path = Path(budget_shim_path).resolve()

    if not resolved_socket_path.exists():
        raise RuntimeError(
            f"Budget broker socket does not exist: {resolved_socket_path}"
        )

    if not resolved_shim_path.is_file():
        raise RuntimeError(
            f"Trusted Aider budget shim does not exist: {resolved_shim_path}"
        )

    return resolved_socket_path, resolved_shim_path


def _validate_resolv_conf(resolv_conf_path: Path | None) -> Path:
    """Resolve and validate the DNS resolver configuration to expose.

    Defaults to /etc/resolv.conf when not explicitly provided.

    Raises:
        RuntimeError: If the resolved path is not a regular file.
    """
    if resolv_conf_path is None:
        resolv_conf_path = Path("/etc/resolv.conf")

    resolved = Path(resolv_conf_path).resolve()

    if not resolved.is_file():
        raise RuntimeError(
            f"Sandbox DNS resolver configuration does not exist: {resolved}"
        )

    return resolved


def _resolve_aider_runtime(aider_path: Path) -> tuple[Path, Path, Path]:
    """Resolve the uv-managed tool root, Python symlink, and Python root.

    The current Aider installation is a uv-managed tool environment.
    Its launcher lives at ``<tool-root>/bin/aider`` and its Python
    executable may resolve outside the tool root, at
    ``<uv-python-root>/bin/python3.x``. Both trees are mounted read-only
    at their original absolute paths.

    Returns:
        A tuple of (tool_root, python_symlink, python_runtime_root).

    Raises:
        RuntimeError: If the virtual-environment Python symlink or its
            resolved runtime root are missing.
    """
    tool_root = aider_path.parent.parent
    python_symlink = tool_root / "bin" / "python"

    if not python_symlink.is_file():
        raise RuntimeError(
            f"Aider virtual-environment Python missing: {python_symlink}"
        )

    python_runtime_root = python_symlink.resolve().parent.parent

    if not python_runtime_root.is_dir():
        raise RuntimeError(
            f"Aider Python runtime root missing: {python_runtime_root}"
        )

    return tool_root, python_symlink, python_runtime_root


def _build_sandbox_home_paths(host_home: Path) -> tuple[str, str]:
    """Compute the synthetic /home paths used inside the sandbox namespace.

    The sandbox HOME is derived from the host user's name only to keep
    a stable, human-readable path; the host home directory itself is
    never mounted into the sandbox.

    Returns:
        A tuple of (user_home, isolated_home) absolute paths as they
        will appear inside the sandbox.
    """
    user_home = f"/home/{host_home.name}"
    isolated_home = f"{user_home}/{_SANDBOX_HOME_SUBDIR}"
    return user_home, isolated_home


def build_aider_sandbox_command(
    *,
    aider_executable: str,
    worker_root: Path,
    model: str,
    prompt: str,
    relative_files: Sequence[str],
    api_base: str,
    api_key_env: str | None = None,
    api_key: str | None = None,
    budget_socket_path: Path | None = None,
    budget_shim_path: Path | None = None,
    resolv_conf_path: Path | None = None,
) -> list[str]:
    """Build the fail-closed bwrap command used to launch Aider.

    Args:
        aider_executable: Path to the Aider launcher executable.
        worker_root: The disposable worker worktree to expose as
            /workspace inside the sandbox. The authoritative checkout
            must never be passed here.
        model: The model identifier to pass to Aider.
        prompt: The instruction message to pass to Aider.
        relative_files: Paths, relative to the worker root, that Aider
            is permitted to edit.
        api_base: The API base URL exposed to Aider via OLLAMA_API_BASE.
        api_key_env: Optional environment variable name under which to
            expose a development credential to Aider.
        api_key: Optional value for `api_key_env`. Required if
            `api_key_env` is set.
        budget_socket_path: Optional path to the budget broker socket.
            Must be supplied together with `budget_shim_path`.
        budget_shim_path: Optional path to the trusted Aider budget
            shim. Must be supplied together with `budget_socket_path`.
        resolv_conf_path: Optional override for the DNS resolver
            configuration file to expose. Defaults to /etc/resolv.conf.

    Returns:
        The full argv list to execute bwrap with.

    Raises:
        RuntimeError: If bubblewrap is unavailable, any required path
            does not exist, or required credential/budget arguments are
            inconsistent.
    """

    bwrap_executable = _require_bwrap_executable()

    worker_root = _validate_worker_root(worker_root)
    aider_path = _validate_aider_executable(aider_executable)

    _validate_credential(api_key_env, api_key)

    budget_socket_path, budget_shim_path = _validate_budget_wiring(
        budget_socket_path, budget_shim_path
    )

    resolv_conf_path = _validate_resolv_conf(resolv_conf_path)

    tool_root, python_symlink, python_runtime_root = _resolve_aider_runtime(
        aider_path
    )

    host_home = Path.home()
    user_home, isolated_home = _build_sandbox_home_paths(host_home)

    command = [
        bwrap_executable,

        # Runtime dependencies.
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/etc", "/etc",

        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--tmpfs", "/home",
        "--dir", user_home,

        # Aider's uv-managed runtime. Read-only.
        "--ro-bind",
        str(python_runtime_root),
        str(python_runtime_root),

        "--ro-bind",
        str(tool_root),
        str(tool_root),

        # Trusted budget shim: read-only, outside the writable worktree.
        *(
            [
                "--ro-bind",
                str(budget_shim_path),
                f"{_SANDBOX_CONTROL_PATH}/sitecustomize.py",
            ]
            if budget_shim_path is not None
            else []
        ),

        # Dedicated broker socket directory only.
        # The API ledger itself is never mounted.
        *(
            [
                "--ro-bind",
                str(budget_socket_path.parent),
                _SANDBOX_BUDGET_PATH,
            ]
            if budget_socket_path is not None
            else []
        ),

        # DNS configuration only. /etc/resolv.conf is commonly a symlink
        # to systemd-resolved's stub file. Mount the resolved file at its
        # real target so the existing /etc/resolv.conf symlink works.
        "--dir",
        str(resolv_conf_path.parent),
        "--ro-bind",
        str(resolv_conf_path),
        str(resolv_conf_path),

        # ONLY writable project filesystem exposed to Aider.
        "--bind",
        str(worker_root),
        _SANDBOX_WORKSPACE_PATH,

        "--dir",
        isolated_home,

        "--chdir",
        _SANDBOX_WORKSPACE_PATH,

        "--die-with-parent",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",

        "--clearenv",
        "--setenv", "HOME", isolated_home,
        "--setenv",
        "PATH",
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "--setenv", "OLLAMA_API_BASE", api_base,
        "--setenv", "AIDER_CHECK_UPDATE", "0",
        "--setenv", "LITELLM_LOCAL_MODEL_COST_MAP", "True",

        *(
            [
                "--setenv",
                "AIDER_BUDGET_SOCKET",
                f"{_SANDBOX_BUDGET_PATH}/{budget_socket_path.name}",
            ]
            if budget_socket_path is not None
            else []
        ),

        *(
            [
                "--setenv",
                "PYTHONPATH",
                _SANDBOX_CONTROL_PATH,
            ]
            if budget_shim_path is not None
            else []
        ),

        # Keep Aider runtime history out of the worker checkout.
        # The sandbox HOME is disposable and isolated from the repository.
        "--setenv",
        "AIDER_INPUT_HISTORY_FILE",
        isolated_home + "/.aider.input.history",
        "--setenv",
        "AIDER_CHAT_HISTORY_FILE",
        isolated_home + "/.aider.chat.history.md",
        "--setenv",
        "AIDER_LLM_HISTORY_FILE",
        isolated_home + "/.aider.llm.history",

        # Only the explicitly selected development credential is exposed.
        *(
            ["--setenv", api_key_env, api_key]
            if api_key_env and api_key
            else []
        ),

        # Use the uv virtualenv Python directly.
        str(python_symlink),
        str(aider_path),

        "--model",
        model,
        "--message",
        prompt,
        "--no-show-model-warnings",
        "--yes-always",

        # Defense in depth. Parent worker owns Git state.
        "--no-auto-commits",
        "--no-git",

        "--no-gitignore",
        "--map-tokens",
        "0",
        "--no-check-update",
        "--no-analytics",

        *sorted(relative_files),
    ]

    return command
