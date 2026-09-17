import pytest
from engine.sigma_parser import export_to_elastic
from contracts.detection_models import DetectionRule

VALID_UUID = "123e4567-e89b-12d3-a456-426614174000"

def test_export_to_elastic_with_selection():
    rule = DetectionRule(
        rule_id=VALID_UUID,
        title="Test Event ID Rule",
        severity="high",
        logsource={"product": "windows", "category": "security"},
        detection={
            "selection": {"EventID": 4625},
            "field": "value"
        },
        mitre_attack_id="T1003",
        description="Test rule for failed logons"
    )
    result = export_to_elastic(rule)
    assert result == {
        "query": {
            "bool": {
                "must": [
                    {"term": {"EventID": 4625}}
                ]
            }
        }
    }

def test_export_to_elastic_multiple_selection_fields():
    rule = DetectionRule(
        rule_id=VALID_UUID,
        title="Multi-field Rule",
        severity="medium",
        logsource={"product": "linux", "category": "auth"},
        detection={
            "selection": {"EventID": 4624, "UserName": "admin"}
        },
        mitre_attack_id="T1078",
        description="Test rule for multiple fields"
    )
    result = export_to_elastic(rule)
    assert result == {
        "query": {
            "bool": {
                "must": [
                    {"term": {"EventID": 4624}},
                    {"term": {"UserName": "admin"}}
                ]
            }
        }
    }

def test_export_to_elastic_fallback_no_selection():
    rule = DetectionRule(
        rule_id=VALID_UUID,
        title="Fallback Rule",
        severity="low",
        logsource={"product": "generic"},
        detection={
            "EventID": 4672
        },
        mitre_attack_id=None,
        description="Test fallback without selection key"
    )
    result = export_to_elastic(rule)
    assert result == {
        "query": {
            "bool": {
                "must": [
                    {"term": {"EventID": 4672}}
                ]
            }
        }
    }

def test_export_to_elastic_empty_detection():
    rule = DetectionRule(
        rule_id=VALID_UUID,
        title="Empty Detection Rule",
        severity="low",
        logsource={"product": "generic"},
        detection={},
        mitre_attack_id=None,
        description="Test empty detection"
    )
    result = export_to_elastic(rule)
    assert result == {"query": {"bool": {"must": []}}}

def test_export_to_elastic_empty_selection():
    rule = DetectionRule(
        rule_id=VALID_UUID,
        title="Empty Selection Rule",
        severity="low",
        logsource={"product": "generic"},
        detection={"selection": {}},
        mitre_attack_id=None,
        description="Test empty selection dict"
    )
    result = export_to_elastic(rule)
    assert result == {"query": {"bool": {"must": []}}}
