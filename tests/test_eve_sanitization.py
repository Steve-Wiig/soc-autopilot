from __future__ import annotations

import engine.intake_eve as intake_eve
from engine.intake_eve import sanitize_recursive

SAFE_STRING = "safe event value"
HIGH_ENTROPY_STRING = "AKIAEXAMPLE1234567890abcdefghijklmnopqrstuvwxyz1234567890"
SENTINEL = "[REDACTED]"


def _install_fake_redactor(monkeypatch):
    calls = []

    def fake_redact_value(value):
        calls.append(value)

        if value == SAFE_STRING:
            return value

        return SENTINEL

    monkeypatch.setattr(intake_eve, "redact_value", fake_redact_value)
    return calls


def test_safe_string_is_passed_to_redact_value(monkeypatch):
    calls = _install_fake_redactor(monkeypatch)

    assert sanitize_recursive(SAFE_STRING) == SAFE_STRING
    assert calls == [SAFE_STRING]


def test_high_entropy_string_is_passed_to_redact_value(monkeypatch):
    calls = _install_fake_redactor(monkeypatch)

    assert sanitize_recursive(HIGH_ENTROPY_STRING) == SENTINEL
    assert calls == [HIGH_ENTROPY_STRING]


def test_nested_string_in_dict_is_sanitized(monkeypatch):
    calls = _install_fake_redactor(monkeypatch)

    payload = {1: {2: HIGH_ENTROPY_STRING}}

    assert sanitize_recursive(payload) == {1: {2: SENTINEL}}
    assert calls == [HIGH_ENTROPY_STRING]


def test_nested_string_in_list_is_sanitized(monkeypatch):
    calls = _install_fake_redactor(monkeypatch)

    payload = [[HIGH_ENTROPY_STRING]]

    assert sanitize_recursive(payload) == [[SENTINEL]]
    assert calls == [HIGH_ENTROPY_STRING]


def test_integer_preserved(monkeypatch):
    calls = _install_fake_redactor(monkeypatch)

    assert sanitize_recursive(123) == 123
    assert calls == []


def test_boolean_preserved(monkeypatch):
    calls = _install_fake_redactor(monkeypatch)

    assert sanitize_recursive(True) is True
    assert sanitize_recursive(False) is False
    assert calls == []


def test_none_preserved(monkeypatch):
    calls = _install_fake_redactor(monkeypatch)

    assert sanitize_recursive(None) is None
    assert calls == []


def test_mixed_nested_object_sanitizes_strings(monkeypatch):
    calls = _install_fake_redactor(monkeypatch)

    payload = {
        1: SAFE_STRING,
        2: [HIGH_ENTROPY_STRING, 42, False, None, {3: SAFE_STRING}],
        3: {4: HIGH_ENTROPY_STRING},
    }

    expected = {
        1: SAFE_STRING,
        2: [SENTINEL, 42, False, None, {3: SAFE_STRING}],
        3: {4: SENTINEL},
    }

    assert sanitize_recursive(payload) == expected
    assert set(calls) == {SAFE_STRING, HIGH_ENTROPY_STRING}
