import pytest
from engine.sigma_parser import validate_sigma_syntax
from contracts.detection_models import DetectionRule

VALID_RULE_ID = "123e4567-e89b-42d3-a456-426614174000"


def _make_rule(**overrides):
    defaults = {
        "rule_id": VALID_RULE_ID,
        "title": "Test Rule",
        "severity": "high",
        "logsource": {"product": "windows", "category": "process_creation"},
        "detection": {"selection": {"EventID": 4624}, "condition": "selection"},
        "mitre_attack_id": None,
        "description": "A test rule",
    }
    defaults.update(overrides)
    return DetectionRule(**defaults)


def test_valid_rule_returns_no_warnings():
    rule = _make_rule()
    assert validate_sigma_syntax(rule) == []


def test_missing_condition_key():
    rule = _make_rule(detection={"selection": {"EventID": 4624}})
    warnings = validate_sigma_syntax(rule)
    assert "Detection is missing 'condition' key" in warnings


def test_empty_selection():
    rule = _make_rule(detection={"selection": {}, "condition": "selection"})
    warnings = validate_sigma_syntax(rule)
    assert "Detection 'selection' is empty" in warnings


def test_multiple_issues():
    rule = _make_rule(detection={"selection": {}})
    warnings = validate_sigma_syntax(rule)
    assert "Detection is missing 'condition' key" in warnings
    assert "Detection 'selection' is empty" in warnings

def test_contract_canary_rejects_invalid_uuid():
    """
    CANARY TEST: Proves that the DetectionRule contract actively rejects 
    invalid UUIDs, preventing the AI from generating lazy test data.
    """
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="rule_id must be a valid UUID v4 string"):
        DetectionRule(
            rule_id="not-a-valid-uuid",
            title="Canary Test",
            severity="high",
            logsource={"product": "windows"},
            detection={"selection": {"EventID": 4624}, "condition": "selection"}
        )

def test_contract_canary_rejects_invalid_severity():
    """
    CANARY TEST: Proves that the DetectionRule contract actively rejects 
    invalid severity enums, preventing the AI from hallucinating new levels.
    """
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="Input should be 'low', 'medium', 'high' or 'critical'"):
        DetectionRule(
            rule_id="123e4567-e89b-42d3-a456-426614174000",
            title="Canary Test",
            severity="super_critical", # AI hallucination attempt
            logsource={"product": "windows"},
            detection={"selection": {"EventID": 4624}, "condition": "selection"}
        )
