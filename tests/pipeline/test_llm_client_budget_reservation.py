from pathlib import Path


SOURCE = Path("overnight/llm_client.py").read_text()


def test_budget_allow_uses_atomic_reservation():
    assert "return budget.reserve_call(provider, model)" in SOURCE


def test_openrouter_reserves_per_actual_model_attempt():
    marker = '        try:\n            check_quota_or_raise()\n            _enforce_free_tier(model)'
    start = SOURCE.index(marker)
    section = SOURCE[start:start + 1200]

    assert 'if not _budget_allow("openrouter", model):' in section


def test_openrouter_does_not_double_record_after_success():
    start = SOURCE.index("def _call_openrouter")
    end = SOURCE.index("def _call_gemini", start)
    section = SOURCE[start:end]

    assert '_budget_record("openrouter")' not in section


def test_gemini_reserves_before_request():
    start = SOURCE.index("def _call_gemini")
    end = SOURCE.index("def discover_groq_models", start)
    section = SOURCE[start:end]

    assert 'if not _budget_allow("gemini"):' in section
    assert 'requests.post(GEMINI_URL' in section


def test_gemini_does_not_double_record_after_success():
    start = SOURCE.index("def _call_gemini")
    end = SOURCE.index("def discover_groq_models", start)
    section = SOURCE[start:end]

    assert '_budget_record("gemini")' not in section
