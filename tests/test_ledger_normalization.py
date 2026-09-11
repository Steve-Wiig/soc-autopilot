import pytest
import json
from engine.ledger import LedgerEvent, LedgerEventType, parse_ledger_event, SCHEMA_VERSION

def test_observation_creation():
    event = LedgerEvent(type=LedgerEventType.OBSERVATION, payload={"advisory_id": "123"})
    data = event.to_dict()
    assert data["type"] == "OBSERVATION"
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["advisory_id"] == "123"

def test_proposal_creation():
    event = LedgerEvent(type=LedgerEventType.PROPOSAL, payload={"advisory_id": "123", "candidate_hash": "abc"})
    data = event.to_dict()
    assert data["type"] == "PROPOSAL"
    assert data["candidate_hash"] == "abc"

def test_promotion_creation():
    event = LedgerEvent(type=LedgerEventType.PROMOTION, payload={"candidate_hash": "abc", "state": "MERGED"})
    data = event.to_dict()
    assert data["type"] == "PROMOTION"
    assert data["state"] == "MERGED"

def test_parse_valid_event():
    json_str = '{"id": "xyz", "type": "OBSERVATION", "advisory_id": "123", "schema_version": 2, "timestamp": "2026-09-11T00:00:00"}'
    event = parse_ledger_event(json_str)
    assert event.type == LedgerEventType.OBSERVATION
    assert event.id == "xyz"
    assert event.payload["advisory_id"] == "123"

def test_parse_invalid_json():
    with pytest.raises(ValueError, match="Invalid JSON"):
        parse_ledger_event("{invalid json")

def test_parse_missing_type():
    with pytest.raises(ValueError, match="Missing 'type'"):
        parse_ledger_event('{"schema_version": 2, "advisory_id": "123"}')

def test_parse_wrong_event_type():
    with pytest.raises(ValueError, match="Unknown event type"):
        parse_ledger_event('{"type": "UNKNOWN_TYPE", "schema_version": 2}')

def test_parse_promotion_missing_state():
    with pytest.raises(ValueError, match="missing required 'state'"):
        parse_ledger_event('{"type": "PROMOTION", "candidate_hash": "abc", "schema_version": 2}')
