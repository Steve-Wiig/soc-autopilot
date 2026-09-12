"""
Tests for P0-5: HMAC-signed worker votes.
"""
import hmac
import hashlib
import os

import pytest

from engine.worker_vote import (
    WorkerIdentity,
    validate_worker_vote,
    check_quorum_with_identity,
    WORKER_VOTE_HMAC_KEY_ENV,
)


KEY = b"test-key-do-not-use-in-prod"


def _make_vote(worker_id="w1", candidate_hash="abc123", decision="approve", key=KEY, ts="2026-01-01T00:00:00"):
    fields = {
        "worker_id": worker_id,
        "worker_class": "critic",
        "worker_instance": f"instance-{worker_id}",
        "execution_host": "host-a",
        "software_version": "1.0.0",
        "candidate_hash": candidate_hash,
        "decision": decision,
        "timestamp": ts,
    }
    identity = WorkerIdentity(**fields)
    sig = identity.compute_signature(key)
    return {**fields, "signature": sig}


def test_valid_signed_vote_accepted(monkeypatch):
    monkeypatch.setenv(WORKER_VOTE_HMAC_KEY_ENV, KEY.decode())
    vote = _make_vote()
    assert validate_worker_vote(vote, "abc123") is True


def test_missing_signature_rejected(monkeypatch):
    monkeypatch.setenv(WORKER_VOTE_HMAC_KEY_ENV, KEY.decode())
    vote = _make_vote()
    del vote["signature"]
    assert validate_worker_vote(vote, "abc123") is False


def test_tampered_decision_rejected(monkeypatch):
    monkeypatch.setenv(WORKER_VOTE_HMAC_KEY_ENV, KEY.decode())
    vote = _make_vote()
    vote["decision"] = "reject"
    assert validate_worker_vote(vote, "abc123") is False


def test_wrong_candidate_hash_rejected(monkeypatch):
    monkeypatch.setenv(WORKER_VOTE_HMAC_KEY_ENV, KEY.decode())
    vote = _make_vote()
    assert validate_worker_vote(vote, "different-hash") is False


def test_signature_from_wrong_key_rejected(monkeypatch):
    monkeypatch.setenv(WORKER_VOTE_HMAC_KEY_ENV, KEY.decode())
    vote = _make_vote(key=b"attacker-key")
    assert validate_worker_vote(vote, "abc123") is False


def test_missing_env_key_fails_closed(monkeypatch):
    monkeypatch.delenv(WORKER_VOTE_HMAC_KEY_ENV, raising=False)
    vote = _make_vote()
    assert validate_worker_vote(vote, "abc123") is False


def test_quorum_accepts_three_distinct_workers(monkeypatch):
    monkeypatch.setenv(WORKER_VOTE_HMAC_KEY_ENV, KEY.decode())
    votes = [_make_vote(worker_id=f"w{i}") for i in range(1, 4)]
    assert check_quorum_with_identity(votes, "abc123") is True


def test_quorum_rejects_duplicate_worker_ids(monkeypatch):
    monkeypatch.setenv(WORKER_VOTE_HMAC_KEY_ENV, KEY.decode())
    votes = [
        _make_vote(worker_id="w1"),
        _make_vote(worker_id="w1", ts="2026-01-02T00:00:00"),
        _make_vote(worker_id="w2"),
    ]
    assert check_quorum_with_identity(votes, "abc123") is False


def test_quorum_rejects_unsigned_vote(monkeypatch):
    monkeypatch.setenv(WORKER_VOTE_HMAC_KEY_ENV, KEY.decode())
    votes = [
        _make_vote(worker_id="w1"),
        _make_vote(worker_id="w2"),
        _make_vote(worker_id="w3"),
    ]
    votes[1]["signature"] = "deadbeef" * 8
    assert check_quorum_with_identity(votes, "abc123") is False


def test_quorum_requires_minimum_count(monkeypatch):
    monkeypatch.setenv(WORKER_VOTE_HMAC_KEY_ENV, KEY.decode())
    votes = [_make_vote(worker_id=f"w{i}") for i in range(1, 3)]  # only 2
    assert check_quorum_with_identity(votes, "abc123", required_count=3) is False
