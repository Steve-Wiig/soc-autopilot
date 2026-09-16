import yaml
from typing import Optional
from pydantic import ValidationError
from contracts.detection_models import DetectionRule

class SigmaParserError(Exception):
    """Base exception for Sigma parsing errors."""
    pass

def parse_sigma_rule(yaml_str: str) -> DetectionRule:
    """
    Parse a Sigma rule from a YAML string into a DetectionRule model.
    Strictly validates required fields via Pydantic.
    """
    if not yaml_str or not yaml_str.strip():
        raise SigmaParserError("Empty YAML content")
        
    try:
        rule_data = yaml.safe_load(yaml_str)
        if not isinstance(rule_data, dict):
            raise SigmaParserError("YAML content must be a dictionary")
            
        # Map common Sigma fields to our DetectionRule model.
        # We intentionally omit default fallbacks for required fields 
        # so Pydantic can enforce strict validation and raise ValidationError.
        mapped_data = {
            "rule_id": rule_data.get("id"),
            "title": rule_data.get("title"),
            "severity": str(rule_data.get("level")).lower() if rule_data.get("level") else None,
            "logsource": rule_data.get("logsource"),
            "detection": rule_data.get("detection"),
            "mitre_attack_id": rule_data.get("tags", [None])[0] if isinstance(rule_data.get("tags"), list) else None,
            "description": rule_data.get("description")
        }
        
        return DetectionRule(**mapped_data)
        
    except yaml.YAMLError as e:
        raise SigmaParserError(f"YAML parsing error: {str(e)}")
    except ValidationError as e:
        raise SigmaParserError(f"Validation error: {str(e)}")
    except Exception as e:
        raise SigmaParserError(f"Unexpected error: {str(e)}")
