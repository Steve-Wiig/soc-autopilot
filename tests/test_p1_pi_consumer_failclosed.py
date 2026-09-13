"""P1-3: pi_consumer must fail closed on missing credentials and must be
importable without side effects (no Redis connection at import time)."""
import sys

import pytest


def _fresh_import():
    if "edge.pi_consumer" in sys.modules:
        del sys.modules["edge.pi_consumer"]
    import edge.pi_consumer as m
    return m


def test_module_imports_without_hanging_or_connecting():
    """Import must not block on r.blpop and must not require Redis."""
    m = _fresh_import()
    assert callable(m.main)
    assert callable(m.dynamic_thermal_pace)
    assert callable(m._verify_job_signature)


def test_main_fails_closed_without_redis_password(monkeypatch):
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.delenv("SOC_ALLOW_UNAUTHENTICATED_REDIS", raising=False)
    monkeypatch.setenv("HMAC_SECRET", "x")
    m = _fresh_import()
    with pytest.raises(RuntimeError, match="REDIS_PASSWORD"):
        m.main()


def test_main_fails_closed_on_changeme_placeholder(monkeypatch):
    monkeypatch.setenv("REDIS_PASSWORD", "CHANGE_ME")
    monkeypatch.delenv("SOC_ALLOW_UNAUTHENTICATED_REDIS", raising=False)
    monkeypatch.setenv("HMAC_SECRET", "x")
    m = _fresh_import()
    with pytest.raises(RuntimeError, match="REDIS_PASSWORD"):
        m.main()


def test_main_fails_closed_without_hmac_secret(monkeypatch):
    monkeypatch.setenv("REDIS_PASSWORD", "realpw")
    monkeypatch.delenv("SOC_ALLOW_UNAUTHENTICATED_REDIS", raising=False)
    monkeypatch.delenv("HMAC_SECRET", raising=False)
    m = _fresh_import()
    with pytest.raises(RuntimeError, match="HMAC_SECRET"):
        m.main()
