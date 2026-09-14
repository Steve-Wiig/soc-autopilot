from pathlib import Path

import engine.aider_sandbox as sandbox


import shutil
def _fake_aider_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"

    tool_root = (
        home
        / ".local"
        / "share"
        / "uv"
        / "tools"
        / "aider-chat"
    )

    python_root = (
        home
        / ".local"
        / "share"
        / "uv"
        / "python"
        / "cpython-test"
    )

    (tool_root / "bin").mkdir(parents=True)
    (python_root / "bin").mkdir(parents=True)

    aider = tool_root / "bin" / "aider"
    python = tool_root / "bin" / "python"
    real_python = python_root / "bin" / "python3"

    aider.write_text("#!/bin/sh\n")
    real_python.write_text("#!/bin/sh\n")
    python.symlink_to(real_python)

    return tool_root, python_root, aider


def test_build_requires_bwrap(tmp_path, monkeypatch):
    _, _, aider = _fake_aider_tree(tmp_path)

    monkeypatch.setattr(
        sandbox.shutil,
        "which",
        lambda name: None if name == "bwrap" else "/usr/bin/" + name,
    )

    try:
        sandbox.build_aider_sandbox_command(
            aider_executable=str(aider),
            worker_root=tmp_path / "worker",
            model="fake/model",
            prompt="test",
            relative_files=["allowed.txt"],
            api_base="http://127.0.0.1:11434",
        )
    except RuntimeError as exc:
        assert "bubblewrap" in str(exc)
    else:
        raise AssertionError("sandbox did not fail closed")


def test_build_bwrap_command_contains_required_containment(tmp_path, monkeypatch):
    tool_root, python_root, aider = _fake_aider_tree(tmp_path)

    worker = tmp_path / "worker"
    worker.mkdir()

    monkeypatch.setattr(
        sandbox.shutil,
        "which",
        lambda name: "/usr/bin/bwrap"
        if name == "bwrap"
        else "/usr/bin/" + name,
    )

    command = sandbox.build_aider_sandbox_command(
        aider_executable=str(aider),
        worker_root=worker,
        model="fake/model",
        prompt="bounded maintenance",
        relative_files=["allowed.txt"],
        api_base="http://127.0.0.1:11434",
    )

    assert command[0] == "/usr/bin/bwrap"

    def has_pair(a, b):
        for i in range(len(command) - 1):
            if command[i] == a and command[i + 1] == b:
                return True
        return False

    assert has_pair("--bind", str(worker.resolve()))
    assert "/workspace" in command

    assert has_pair("--ro-bind", str(tool_root.resolve()))
    assert str(python_root.resolve()) in command

    assert "--clearenv" in command
    assert "--unshare-user" in command
    assert "--unshare-pid" in command
    assert "--unshare-ipc" in command
    assert "--unshare-uts" in command

    assert "--no-git" in command
    assert "--no-auto-commits" in command

    # Authoritative repo paths are never accepted as a mount argument.
    assert str(worker.resolve()) in command
    assert "/workspace" in command


def test_build_has_no_authoritative_repo_mount(tmp_path, monkeypatch):
    _, _, aider = _fake_aider_tree(tmp_path)

    worker = tmp_path / "worker"
    authoritative = tmp_path / "authoritative"

    worker.mkdir()
    authoritative.mkdir()

    monkeypatch.setattr(
        sandbox.shutil,
        "which",
        lambda name: "/usr/bin/bwrap"
        if name == "bwrap"
        else "/usr/bin/" + name,
    )

    command = sandbox.build_aider_sandbox_command(
        aider_executable=str(aider),
        worker_root=worker,
        model="fake/model",
        prompt="test",
        relative_files=["allowed.txt"],
        api_base="http://127.0.0.1:11434",
    )

    assert str(authoritative.resolve()) not in command

def test_dns_resolver_is_bound_read_only(tmp_path):
    from engine.aider_sandbox import build_aider_sandbox_command

    worker = tmp_path / "worker"
    worker.mkdir()

    resolver = tmp_path / "resolv.conf"
    resolver.write_text(
        "nameserver 127.0.0.53\n"
    )

    aider = shutil.which("aider")
    assert aider is not None

    command = build_aider_sandbox_command(
        aider_executable=aider,
        worker_root=worker,
        model="ollama_chat/qwen2.5-coder:3b",
        prompt="probe",
        relative_files=["allowed.txt"],
        api_base="http://127.0.0.1:11434",
        resolv_conf_path=resolver,
    )

    # Exact resolver bind must be present.
    assert "--dir" in command
    assert str(resolver.parent) in command

    bind_index = command.index("--ro-bind")

    matches = [
        i
        for i, value in enumerate(command)
        if value == str(resolver)
    ]

    assert matches
    i = matches[0]
    assert command[i - 1] == "--ro-bind"
    assert command[i + 1] == str(resolver)

