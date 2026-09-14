import json
import socket
from pathlib import Path

from engine.development_budget_broker import DevelopmentBudgetBroker
from overnight.budget_manager import APIBudgetManager


def _budget(tmp_path: Path) -> APIBudgetManager:
    return APIBudgetManager(
        limits={
            "openrouter": {
                "per_minute": 3,
                "per_hour": 3,
                "per_day": 3,
            },
            "gemini": {
                "per_minute": 3,
                "per_hour": 3,
                "per_day": 3,
            },
        },
        usage_file=tmp_path / "api_usage.json",
        lock_file=tmp_path / "api_usage.lock",
    )


def _request(path: Path, payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect(str(path))
        sock.sendall(
            (json.dumps(payload) + "\n").encode()
        )

        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

    return json.loads(data.split(b"\n", 1)[0])


def test_broker_reserves_shared_budget(tmp_path):
    budget = _budget(tmp_path)
    broker = DevelopmentBudgetBroker(
        budget=budget,
        socket_path=tmp_path / "budget.sock",
    )

    broker.start()
    try:
        first = _request(
            tmp_path / "budget.sock",
            {
                "op": "reserve",
                "provider": "openrouter",
                "model": "openrouter/qwen/qwen3-coder",
            },
        )

        second = _request(
            tmp_path / "budget.sock",
            {
                "op": "reserve",
                "provider": "openrouter",
                "model": "openrouter/qwen/qwen3-coder",
            },
        )

        third = _request(
            tmp_path / "budget.sock",
            {
                "op": "reserve",
                "provider": "openrouter",
                "model": "openrouter/qwen/qwen3-coder",
            },
        )

        assert first == {"ok": True, "reserved": True}
        assert second == {"ok": True, "reserved": True}
        assert third == {
            "ok": True,
            "reserved": False,
            "reason": "BUDGET_EXHAUSTED",
        }

        assert budget.get_usage("openrouter")["last_minute"] == 2
    finally:
        broker.stop()


def test_broker_supports_gemini_in_same_authority(tmp_path):
    budget = _budget(tmp_path)
    broker = DevelopmentBudgetBroker(
        budget=budget,
        socket_path=tmp_path / "budget.sock",
    )

    broker.start()
    try:
        result = _request(
            tmp_path / "budget.sock",
            {
                "op": "reserve",
                "provider": "gemini",
                "model": "gemini/gemini-3.8-flash",
            },
        )

        assert result == {"ok": True, "reserved": True}
        assert budget.get_usage("gemini")["last_minute"] == 1
    finally:
        broker.stop()


def test_broker_rejects_invalid_requests(tmp_path):
    budget = _budget(tmp_path)
    broker = DevelopmentBudgetBroker(
        budget=budget,
        socket_path=tmp_path / "budget.sock",
    )

    broker.start()
    try:
        result = _request(
            tmp_path / "budget.sock",
            {
                "op": "evil",
                "provider": "openrouter",
            },
        )

        assert result == {
            "ok": False,
            "error": "UNSUPPORTED_OPERATION",
        }
    finally:
        broker.stop()


def test_broker_socket_is_private_and_removed_on_stop(tmp_path):
    path = tmp_path / "budget.sock"
    broker = DevelopmentBudgetBroker(
        budget=_budget(tmp_path),
        socket_path=path,
    )

    broker.start()
    assert path.exists()
    assert oct(path.stat().st_mode & 0o777) == "0o600"

    broker.stop()

    assert not path.exists()


def test_broker_rejects_invalid_provider(tmp_path):
    broker = DevelopmentBudgetBroker(
        budget=_budget(tmp_path),
        socket_path=tmp_path / "budget.sock",
    )

    broker.start()
    try:
        result = _request(
            tmp_path / "budget.sock",
            {
                "op": "reserve",
                "provider": "",
            },
        )

        assert result == {
            "ok": False,
            "error": "INVALID_PROVIDER",
        }
    finally:
        broker.stop()

def test_broker_rejects_unauthorized_provider(tmp_path):
    broker = DevelopmentBudgetBroker(
        budget=_budget(tmp_path),
        socket_path=tmp_path / "budget.sock",
        allowed_provider="openrouter",
        allowed_model="openrouter/qwen/qwen3-coder",
    )

    broker.start()
    try:
        result = _request(
            tmp_path / "budget.sock",
            {
                "op": "reserve",
                "provider": "gemini",
                "model": "gemini/gemini-3.8-flash",
            },
        )

        assert result == {
            "ok": False,
            "error": "PROVIDER_NOT_AUTHORIZED",
        }
    finally:
        broker.stop()


def test_broker_rejects_unauthorized_model(tmp_path):
    broker = DevelopmentBudgetBroker(
        budget=_budget(tmp_path),
        socket_path=tmp_path / "budget.sock",
        allowed_provider="openrouter",
        allowed_model="openrouter/qwen/qwen3-coder",
    )

    broker.start()
    try:
        result = _request(
            tmp_path / "budget.sock",
            {
                "op": "reserve",
                "provider": "openrouter",
                "model": "openrouter/other-model",
            },
        )

        assert result == {
            "ok": False,
            "error": "MODEL_NOT_AUTHORIZED",
        }
    finally:
        broker.stop()


def test_broker_allows_only_pinned_provider_and_model(tmp_path):
    broker = DevelopmentBudgetBroker(
        budget=_budget(tmp_path),
        socket_path=tmp_path / "budget.sock",
        allowed_provider="openrouter",
        allowed_model="openrouter/qwen/qwen3-coder",
    )

    broker.start()
    try:
        result = _request(
            tmp_path / "budget.sock",
            {
                "op": "reserve",
                "provider": "openrouter",
                "model": "openrouter/qwen/qwen3-coder",
            },
        )

        assert result == {
            "ok": True,
            "reserved": True,
        }
    finally:
        broker.stop()

