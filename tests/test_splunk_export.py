from contracts.detection_models import DetectionRule
from engine.sigma_parser import export_to_splunk

def test_export_to_splunk_with_selection():
    rule = DetectionRule(
        rule_id="123e4567-e89b-12d3-a456-426614174000",
        title="Windows Logon Failure",
        severity="high",
        logsource={"product": "windows", "category": "security"},
        detection={
            "selection": {
                "EventID": 4625,
                "TargetUserName": "*"
            },
            "condition": "selection"
        }
    )
    result = export_to_splunk(rule)
    assert "EventID=4625" in result
    assert "TargetUserName=*" in result

def test_export_to_splunk_empty_detection():
    rule = DetectionRule(
        rule_id="5a2ac236-1b4d-4d6f-9c6f-8f2e1d3a4b5c",
        title="Empty Detection Test",
        severity="medium",
        logsource={"product": "linux"},
        detection={}
    )
    result = export_to_splunk(rule)
    assert result == ""

def test_export_to_splunk_flat_detection():
    rule = DetectionRule(
        rule_id="9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        title="Flat Detection Test",
        severity="low",
        logsource={"product": "aws"},
        detection={
            "eventName": "DescribeInstances",
            "errorCode": "AccessDenied"
        }
    )
    result = export_to_splunk(rule)
    assert "eventName=DescribeInstances" in result
    assert "errorCode=AccessDenied" in result
