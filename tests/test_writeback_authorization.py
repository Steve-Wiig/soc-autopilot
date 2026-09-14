import time

import pytest

from engine.writeback.authorization import (
    WritebackAuthorization,
    WritebackAuthorizationError,
    issue_writeback_authorization,
    parse_writeback_authorization,
)


SECRET = "unit-test-writeback-secret"


def token(
    *,
    decision_id="DEC-TEST-1",
    target="so_cases",
    outcome="ALLOW",
    expires_at=None,
):
    return issue_writeback_authorization(
        decision_id=decision_id,
        target=target,
        outcome=outcome,
        expires_at=expires_at or int(time.time()) + 300,
        secret=SECRET,
    )


def test_valid_authorization_round_trip():
    auth = parse_writeback_authorization(
        token(),
        expected_target="so_cases",
        secret=SECRET,
    )

    assert auth.decision_id == "DEC-TEST-1"
    assert auth.target == "so_cases"
    assert auth.outcome == "ALLOW"


def test_wrong_target_rejected():
    with pytest.raises(WritebackAuthorizationError):
        parse_writeback_authorization(
            token(),
            expected_target="thehive",
            secret=SECRET,
        )


def test_tampered_signature_rejected():
    raw = token()
    encoded, signature = raw.rsplit(".", 1)

    with pytest.raises(WritebackAuthorizationError):
        parse_writeback_authorization(
            f"{encoded}.{'0' * len(signature)}",
            expected_target="so_cases",
            secret=SECRET,
        )


def test_expired_authorization_rejected():
    auth = WritebackAuthorization(
        decision_id="DEC-EXPIRED",
        target="so_cases",
        outcome="ALLOW",
        expires_at=int(time.time()) - 1,
        signature="not-used",
    )

    with pytest.raises(
        WritebackAuthorizationError,
        match="expired",
    ):
        auth.validate(
            expected_target="so_cases",
            secret=SECRET,
        )


def test_review_cannot_authorize():
    with pytest.raises(WritebackAuthorizationError):
        issue_writeback_authorization(
            decision_id="DEC-TEST-REVIEW",
            target="so_cases",
            outcome="REVIEW",
            expires_at=int(time.time()) + 300,
            secret=SECRET,
        )


def test_missing_secret_rejected(monkeypatch):
    monkeypatch.delenv("SOC_WRITEBACK_AUTH_SECRET", raising=False)

    with pytest.raises(WritebackAuthorizationError):
        parse_writeback_authorization(
            token(),
            expected_target="so_cases",
            secret=None,
        )


def test_generic_executor_fails_closed():
    from engine.writeback import WritebackEngine

    with pytest.raises(
        RuntimeError,
        match="Generic writeback execution is disabled",
    ):
        WritebackEngine({}).execute({}, "anything")
