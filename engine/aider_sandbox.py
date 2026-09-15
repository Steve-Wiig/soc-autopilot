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
    """Build the fail-closed bwrap command used to launch Aider."""

    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError(
            "Aider sandbox requires bubblewrap (bwrap); "
            "refusing unsandboxed execution."
        )

    worker_root = Path(worker_root).resolve()

    if not worker_root.is_dir():
        raise RuntimeError(
            f"Aider sandbox worker root does not exist: {worker_root}"
        )

    aider_path = Path(aider_executable).resolve()

    if not aider_path.is_file():
        raise RuntimeError(
            f"Aider executable does not exist: {aider_path}"
        )

    if api_key_env and not api_key:
        raise RuntimeError(
            f"Required development credential is missing: {api_key_env}"
        )

    if (budget_socket_path is None) != (budget_shim_path is None):
        raise RuntimeError(
            "Budget socket and budget shim must be supplied together."
        )

    if budget_socket_path is not None:
        budget_socket_path = Path(budget_socket_path).resolve()
        budget_shim_path = Path(budget_shim_path).resolve()

        if not budget_socket_path.exists():
            raise RuntimeError(
                f"Budget broker socket does not exist: {budget_socket_path}"
            )

        if not budget_shim_path.is_file():
            raise RuntimeError(
                f"Trusted Aider budget shim does not exist: {budget_shim_path}"
            )

    if resolv_conf_path is None:
        resolv_conf_path = Path("/etc/resolv.conf")

    resolv_conf_path = Path(resolv_conf_path).resolve()

    if not resolv_conf_path.is_file():
        raise RuntimeError(
            f"Sandbox DNS resolver configuration does not exist: {resolv_conf_path}"
        )

    # Current Aider installation is a uv-managed tool environment.
    #
    # The launcher lives at:
    #   <tool-root>/bin/aider
    #
    # Its Python executable may resolve outside the tool root:
    #   <uv-python-root>/bin/python3.x
    #
    # Both trees are mounted read-only at their original absolute paths.
    tool_root = aider_path.parent.parent
    python_link = tool_root / "bin" / "python"

    if not python_link.is_file():
        raise RuntimeError(
            f"Aider virtual-environment Python missing: {python_link}"
        )

    python_path = python_link.resolve()
    python_root = python_path.parent.parent

    if not python_root.is_dir():
        raise RuntimeError(
            f"Aider Python runtime root missing: {python_root}"
        )

    host_home = Path.home()
    sandbox_home = host_home / ".soc-autopilot-aider-sandbox-home"

    # sandbox_home is inside the synthetic /home tmpfs; the host path is only
    # used to derive a stable user name and is never mounted.
    user_home = f"/home/{host_home.name}"
    isolated_home = f"{user_home}/sandbox-home"

    command = [
        bwrap,

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
        str(python_root),
        str(python_root),

        "--ro-bind",
        str(tool_root),
        str(tool_root),

        # Trusted budget shim: read-only, outside the writable worktree.
        *(
            [
                "--ro-bind",
                str(budget_shim_path),
                "/aider-control/sitecustomize.py",
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
                "/aider-budget",
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
        "/workspace",

        "--dir",
        isolated_home,

        "--chdir",
        "/workspace",

        "--share-net --die-with-parent",
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
                "/aider-budget/" + budget_socket_path.name,
            ]
            if budget_socket_path is not None
            else []
        ),

        *(
            [
                "--setenv",
                "PYTHONPATH",
                "/aider-control",
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
        str(python_link),
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
