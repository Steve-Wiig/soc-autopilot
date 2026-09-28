import sys
import os
from typing import TYPE_CHECKING

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# TYPE_CHECKING is False at runtime, preventing the circular import,
# but IDEs and type checkers still see it for autocomplete.
if TYPE_CHECKING:
    from tools.alert_pipeline import EnrichedAlert

def generate_sigma_rule(alert: 'EnrichedAlert') -> str:
    """
    Generates a valid YAML string for a Sigma rule based on the given EnrichedAlert.
    """
    level_mapping = {
        'low': 'low', 'medium': 'medium', 'high': 'high',
        'critical': 'critical', 'informational': 'informational'
    }
    
    # Handle both string and enum-like severity safely
    severity = str(getattr(alert, 'normalized_severity', 'informational')).lower()
    level = level_mapping.get(severity, 'informational')
    
    src_ip = getattr(alert, 'src_ip', '0.0.0.0')
    rule_name = getattr(alert, 'rule_name', 'Unknown_Rule')
    mitre_technique = getattr(alert, 'mitre_technique', 'Unknown')
    
    return f"""title: "Alert from {rule_name}"
description: "Auto-generated Sigma rule for {rule_name} (MITRE: {mitre_technique})"
logsource:
  product: linux
detection:
  selection:
    rule_name: "{rule_name}"
    src_ip: "{src_ip}"
    mitre_technique: "{mitre_technique}"
  condition: selection
level: {level}
"""
