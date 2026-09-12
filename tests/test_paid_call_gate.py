"""Tests for the paid-call gate in overnight/llm_client.py."""
import pytest
from overnight.llm_client import _enforce_free_tier

PAID = "anthropic/claude-3.5-sonnet"
FREE = "nvidia/nemotron-3.5-lightning:free"

def test_default_blocks_paid(monkeypatch):
    monkeypatch.delenv("ALLOW_PAID_CALLS", raising=False)
    with pytest.raises(RuntimeError, match="SECURITY VIOLATION"):
        _enforce_free_tier(PAID)

def test_default_allows_free(monkeypatch):
    monkeypatch.delenv("ALLOW_PAID_CALLS", raising=False)
    _enforce_free_tier(FREE)

def test_true_allows_paid(monkeypatch):
    monkeypatch.setenv("ALLOW_PAID_CALLS", "true")
    _enforce_free_tier(PAID)

def test_true_allows_free(monkeypatch):
    monkeypatch.setenv("ALLOW_PAID_CALLS", "true")
    _enforce_free_tier(FREE)

@pytest.mark.parametrize("val", ["true", "True", "TRUE", "tRuE"])
def test_truthy_values_allow(monkeypatch, val):
    monkeypatch.setenv("ALLOW_PAID_CALLS", val)
    _enforce_free_tier(PAID)

@pytest.mark.parametrize("val", ["false", "False", "FALSE", "0", "1", "no", "yes", "", "off", "on", "garbage"])
def test_non_true_values_block(monkeypatch, val):
    monkeypatch.setenv("ALLOW_PAID_CALLS", val)
    with pytest.raises(RuntimeError, match="SECURITY VIOLATION"):
        _enforce_free_tier(PAID)

def test_whitespace_free_stripped(monkeypatch):
    monkeypatch.delenv("ALLOW_PAID_CALLS", raising=False)
    _enforce_free_tier("   " + FREE + "   ")

def test_whitespace_paid_blocked(monkeypatch):
    monkeypatch.delenv("ALLOW_PAID_CALLS", raising=False)
    with pytest.raises(RuntimeError):
        _enforce_free_tier("   " + PAID + "   ")

def test_nested_free_suffix(monkeypatch):
    monkeypatch.delenv("ALLOW_PAID_CALLS", raising=False)
    _enforce_free_tier("some-org/some-model:free")

def test_paid_no_suffix_blocked(monkeypatch):
    monkeypatch.delenv("ALLOW_PAID_CALLS", raising=False)
    with pytest.raises(RuntimeError):
        _enforce_free_tier("some-org/some-model")
