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
