import json
import os
import socket
import sys
import types


def _load_shim(monkeypatch, socket_path):
    monkeypatch.setenv("AIDER_BUDGET_SOCKET", str(socket_path))

    litellm = types.SimpleNamespace()

    calls = []

    def completion(*args, **kwargs):
        calls.append(kwargs)
        return "MODEL_CALLED"

    litellm.completion = completion
    sys.modules["litellm"] = litellm

    module_name = "engine.aider_budget_shim"
    sys.modules.pop(module_name, None)

    import importlib

    module = importlib.import_module(module_name)
    return module, calls


def _server(path, response):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)

    conn, _ = server.accept()
    with conn:
        data = b""
        while b"\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk

        request = json.loads(data.split(b"\n", 1)[0])
        conn.sendall((json.dumps(response) + "\n").encode())

    server.close()
    return request


def test_local_model_does_not_use_broker(tmp_path, monkeypatch):
    socket_path = tmp_path / "budget.sock"
    module, calls = _load_shim(monkeypatch, socket_path)

    result = module.litellm.completion(
        model="ollama_chat/qwen2.5-coder:3b",
        messages=[],
    )

    assert result == "MODEL_CALLED"
    assert calls[0]["model"] == "ollama_chat/qwen2.5-coder:3b"


def test_openrouter_requires_broker_reservation(tmp_path, monkeypatch):
    socket_path = tmp_path / "budget.sock"
    module, calls = _load_shim(monkeypatch, socket_path)

    request = {}

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    try:
        import threading

        def serve():
            conn, _ = server.accept()
            with conn:
                data = b""
                while b"\n" not in data:
                    data += conn.recv(4096)

                request.update(
                    json.loads(data.split(b"\n", 1)[0])
                )

                conn.sendall(
                    b'{"ok":true,"reserved":true}\n'
                )

        thread = threading.Thread(target=serve)
        thread.start()

        result = module.litellm.completion(
            model="openrouter/qwen/qwen3-coder",
            messages=[],
        )

        thread.join(timeout=2)

        assert result == "MODEL_CALLED"
        assert request == {
            "op": "reserve",
            "provider": "openrouter",
            "model": "openrouter/qwen/qwen3-coder",
        }
        assert len(calls) == 1
    finally:
        server.close()


def test_cloud_request_is_blocked_when_budget_denied(tmp_path, monkeypatch):
    socket_path = tmp_path / "budget.sock"
    module, calls = _load_shim(monkeypatch, socket_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    try:
        import threading

        def serve():
            conn, _ = server.accept()
            with conn:
                while b"\n" not in conn.recv(4096):
                    pass
                conn.sendall(
                    b'{"ok":true,"reserved":false,"reason":"BUDGET_EXHAUSTED"}\n'
                )

        thread = threading.Thread(target=serve)
        thread.start()

        try:
            module.litellm.completion(
                model="gemini/gemini-3.8-flash",
                messages=[],
            )
        except RuntimeError as exc:
            assert "BUDGET_EXHAUSTED" in str(exc)
        else:
            raise AssertionError("cloud request was not blocked")

        thread.join(timeout=2)
        assert calls == []
    finally:
        server.close()


def test_cloud_request_fails_closed_without_broker(tmp_path, monkeypatch):
    monkeypatch.delenv("AIDER_BUDGET_SOCKET", raising=False)

    import types

    litellm = types.SimpleNamespace(
        completion=lambda **kwargs: "MODEL_CALLED"
    )
    sys.modules["litellm"] = litellm

    import importlib

    module_name = "engine.aider_budget_shim"
    sys.modules.pop(module_name, None)

    module = importlib.import_module(module_name)

    try:
        module.litellm.completion(
            model="openrouter/qwen/qwen3-coder",
            messages=[],
        )
    except RuntimeError as exc:
        assert "AIDER_BUDGET_SOCKET" in str(exc)
    else:
        raise AssertionError("cloud request did not fail closed")

def test_metadata_url_policy_blocks_remote_metadata():
    module, _ = _load_shim(
        __import__("pytest").MonkeyPatch(),
        __import__("pathlib").Path("/tmp/nonexistent-budget.sock"),
    )

    assert module._is_blocked_metadata_url(
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    )

    assert module._is_blocked_metadata_url(
        "https://openrouter.ai/qwen/qwen3-coder"
    )

    assert not module._is_blocked_metadata_url(
        "https://openrouter.ai/api/v1/chat/completions"
    )

    assert not module._is_blocked_metadata_url(
        "https://generativelanguage.googleapis.com/v1beta/models"
    )


def test_metadata_network_gate_blocks_requests(monkeypatch):
    import requests

    import engine.aider_budget_shim as module

    # Force a clean gate installation state for this test.
    monkeypatch.setattr(
        requests.sessions.Session,
        "request",
        requests.sessions.Session.request,
    )

    monkeypatch.delattr(
        requests,
        "_soc_autopilot_metadata_gate_installed",
        raising=False,
    )

    module._install_metadata_network_gate()

    with __import__("pytest").raises(RuntimeError, match="metadata network request blocked"):
        requests.get(
            "https://raw.githubusercontent.com/BerriAI/litellm/main/"
            "model_prices_and_context_window.json"
        )

