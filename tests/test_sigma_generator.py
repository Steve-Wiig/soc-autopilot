import sys
import os
import pytest
from typing import TYPE_CHECKING
from tools.alert_pipeline import EnrichedAlert
from tools.sigma_generator import generate_sigma_rule
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# TYPE_CHECKING is False at runtime, preventing the circular import,
# but IDEs and type checkers still see it for autocomplete.
if TYPE_CHECKING:
    from tools.alert_pipeline import EnrichedAlert

def test_generate_sigma_rule():
    """
    Test that the generate_sigma_rule function produces a valid YAML string with the expected content.
    """
    alert = EnrichedAlert(
        timestamp="2023-04-01T12:00:00Z",
        src_ip="1.2.3.4",
        dst_ip="5.6.7.8",
        rule_name="ExampleRule",
        original_severity="high",
        normalized_severity="High",
        is_malicious_ip=True,
        mitre_technique="T1071"
    )
    sigma_rule = generate_sigma_rule(alert)
    assert 'title:' in sigma_rule
    assert 'detection:' in sigma_rule
    assert 'T1071' in sigma_rule

def test_generate_sigma_rule_parsing():
    """
    Test that the generated YAML string can be successfully parsed by the 'yaml' module.
    """
    alert = EnrichedAlert(
        timestamp="2023-04-01T12:00:00Z",
        src_ip="1.2.3.4",
        dst_ip="5.6.7.8",
        rule_name="ExampleRule",
        original_severity="high",
        normalized_severity="High",
        is_malicious_ip=True,
        mitre_technique="T1071"
    )
    sigma_rule = generate_sigma_rule(alert)
    try:
        yaml.safe_load(sigma_rule)
    except yaml.YAMLError as exc:
        pytest.fail(f"Failed to parse YAML: {exc}")
