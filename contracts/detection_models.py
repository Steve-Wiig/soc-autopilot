from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class DetectionRule(BaseModel):
    """Model representing a parsed Sigma detection rule."""
    rule_id: str = Field(..., description="Unique identifier for the rule")
    title: str = Field(..., description="Human-readable title of the rule")
    severity: str = Field(..., description="Severity level (e.g., low, medium, high, critical)")
    logsource: Dict[str, str] = Field(..., description="The log source this rule applies to")
    detection: Dict[str, Any] = Field(..., description="The detection logic and conditions")
    mitre_attack_id: Optional[str] = Field(None, description="Associated MITRE ATT&CK technique ID")
    description: Optional[str] = Field(None, description="Detailed description of the rule")
