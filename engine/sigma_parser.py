from typing import Any, Dict, List

import yaml
from pydantic import ValidationError

from contracts.detection_models import DetectionRule


class SigmaParserError(Exception):
    """Base exception for Sigma parsing errors."""
    pass


def parse_sigma_rule(yaml_str: str) -> DetectionRule:
    """
    Parse a Sigma rule from a YAML string into a DetectionRule model.

    Strictly validates required fields via Pydantic.

    Args:
        yaml_str: Raw YAML content representing a Sigma rule.

    Returns:
        A validated DetectionRule instance.

    Raises:
        SigmaParserError: If the YAML is empty, malformed, not a dictionary,
            or fails DetectionRule validation.
    """
    if not yaml_str or not yaml_str.strip():
        raise SigmaParserError("Empty YAML content")

    try:
        rule_data: Any = yaml.safe_load(yaml_str)
        if not isinstance(rule_data, dict):
            raise SigmaParserError("YAML content must be a dictionary")

        # Map common Sigma fields to our DetectionRule model.
        # We intentionally omit default fallbacks for required fields
        # so Pydantic can enforce strict validation and raise ValidationError.
        mapped_data: Dict[str, Any] = {
            "rule_id": rule_data.get("id"),
            "title": rule_data.get("title"),
            "severity": str(rule_data.get("level")).lower() if rule_data.get("level") else None,
            "logsource": rule_data.get("logsource"),
            "detection": rule_data.get("detection"),
            "mitre_attack_id": rule_data.get("tags", [None])[0] if isinstance(rule_data.get("tags"), list) else None,
            "description": rule_data.get("description"),
        }

        return DetectionRule(**mapped_data)

    except yaml.YAMLError as exc:
        raise SigmaParserError(f"YAML parsing error: {str(exc)}") from exc
    except ValidationError as exc:
        raise SigmaParserError(f"Validation error: {str(exc)}") from exc
    except Exception as exc:
        raise SigmaParserError(f"Unexpected error: {str(exc)}") from exc


def export_to_splunk(rule: DetectionRule) -> str:
    """
    Translate the DetectionRule's detection dict into a basic Splunk SPL query string.

    Args:
        rule: The DetectionRule whose detection logic should be exported.

    Returns:
        A space-separated string of "field=value" pairs suitable for a basic
        Splunk SPL search, or an empty string if no detection data is present.
    """
    if not rule.detection or not isinstance(rule.detection, dict):
        return ""

    # Sigma rules typically define a 'selection' dict with field:value pairs
    selection: Dict[str, Any] = rule.detection.get("selection", {})
    if isinstance(selection, dict) and selection:
        return " ".join(f"{field}={value}" for field, value in selection.items())

    # Fallback: treat top-level non-dict values as field=value pairs
    parts: List[str] = []
    for key, value in rule.detection.items():
        if not isinstance(value, dict):
            parts.append(f"{key}={value}")

    return " ".join(parts)


def export_to_elastic(rule: DetectionRule) -> Dict[str, Any]:
    """
    Translate the DetectionRule's detection dict into a basic Elastic Query DSL dictionary.

    Args:
        rule: The DetectionRule whose detection logic should be exported.

    Returns:
        A dict in the form:
            {'query': {'bool': {'must': [{'term': {'Field': value}}, ...]}}}
        with an empty 'must' list if no detection data is present.
    """
    if not rule.detection or not isinstance(rule.detection, dict):
        return {"query": {"bool": {"must": []}}}

    selection: Dict[str, Any] = rule.detection.get("selection", {})
    if isinstance(selection, dict) and selection:
        must_clauses: List[Dict[str, Any]] = [{"term": {field: value}} for field, value in selection.items()]
        return {"query": {"bool": {"must": must_clauses}}}

    # Fallback: treat top-level non-dict values as term clauses
    must_clauses = []
    for key, value in rule.detection.items():
        if not isinstance(value, dict):
            must_clauses.append({"term": {key: value}})

    return {"query": {"bool": {"must": must_clauses}}}


def validate_sigma_syntax(rule: DetectionRule) -> List[str]:
    """
    Check a DetectionRule for common Sigma anti-patterns.

    Args:
        rule: The DetectionRule to validate.

    Returns:
        A list of human-readable warning messages. Empty if no issues found.
    """
    warnings: List[str] = []

    if rule.detection is None or not isinstance(rule.detection, dict):
        warnings.append("Detection section is empty or invalid")
        return warnings

    if "condition" not in rule.detection:
        warnings.append("Detection is missing 'condition' key")

    selection: Any = rule.detection.get("selection")
    if isinstance(selection, dict) and not selection:
        warnings.append("Detection 'selection' is empty")

    return warnings
