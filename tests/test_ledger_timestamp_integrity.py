import pytest

from engine.ledger import parse_ledger_event


def test_missing_timestamp_is_rejected():
    payload = (
        '{"id":"x1","type":"OBSERVATION",'
        '"schema_version":2}'
    )

    with pytest.raises(ValueError, match="Missing timestamp field"):
        parse_ledger_event(payload)


def test_empty_timestamp_is_rejected():
    payload = (
        '{"id":"x1","type":"OBSERVATION",'
        '"timestamp":"   ","schema_version":2}'
    )

    with pytest.raises(ValueError, match="Missing timestamp field"):
        parse_ledger_event(payload)


def test_valid_timestamp_is_preserved():
    payload = (
        '{"id":"x1","type":"OBSERVATION",'
        '"timestamp":"2026-09-11T13:00:00+00:00",'
        '"schema_version":2}'
    )

    event = parse_ledger_event(payload)

    assert event.timestamp == "2026-09-11T13:00:00+00:00"
