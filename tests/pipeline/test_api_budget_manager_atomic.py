from pathlib import Path

from overnight.budget_manager import APIBudgetManager


def _manager(tmp_path: Path) -> APIBudgetManager:
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


def test_reserve_call_atomically_consumes_budget(tmp_path):
    manager = _manager(tmp_path)

    # 3 * 0.85 => effective limit 2.
    assert manager.reserve_call("openrouter") is True
    assert manager.reserve_call("openrouter") is True
    assert manager.reserve_call("openrouter") is False

    assert manager.get_usage("openrouter")["last_minute"] == 2


def test_reserve_call_is_persisted_for_new_manager(tmp_path):
    first = _manager(tmp_path)

    assert first.reserve_call("openrouter") is True

    second = _manager(tmp_path)

    assert second.get_usage("openrouter")["last_minute"] == 1
    assert second.reserve_call("openrouter") is True
    assert second.reserve_call("openrouter") is False


def test_gemini_uses_same_shared_authority(tmp_path):
    manager = _manager(tmp_path)

    assert manager.reserve_call("gemini") is True
    assert manager.get_usage("gemini")["last_minute"] == 1


def test_reserve_call_rejects_when_budget_is_exhausted(tmp_path):
    manager = APIBudgetManager(
        limits={
            "openrouter": {
                "per_minute": 1,
                "per_hour": 1,
                "per_day": 1,
            }
        },
        usage_file=tmp_path / "api_usage.json",
        lock_file=tmp_path / "api_usage.lock",
    )

    assert manager.reserve_call("openrouter") is True
    assert manager.reserve_call("openrouter") is False
    assert manager.get_usage("openrouter")["last_minute"] == 1
