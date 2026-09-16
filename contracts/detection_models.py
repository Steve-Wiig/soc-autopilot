from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any
from enum import Enum
import uuid

class SeverityLevel(str, Enum):
    """Strict enum for allowed severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class DetectionRule(BaseModel):
    """
    Strict model representing a parsed Sigma detection rule.
    Future-proofed with explicit validation to prevent AI hallucination.
    """
    rule_id: str = Field(..., description="Must be a valid UUID v4 string")
    title: str = Field(..., min_length=5, max_length=200, description="Human-readable title")
    severity: SeverityLevel = Field(..., description="Must be low, medium, high, or critical")
    logsource: Dict[str, str] = Field(..., description="The log source this rule applies to")
    detection: Dict[str, Any] = Field(..., description="The detection logic and conditions")
    mitre_attack_id: Optional[str] = Field(None, pattern=r"^T\d{4}(\.\d{3})?$", description="e.g., T1059 or T1059.001")
    description: Optional[str] = Field(None, min_length=10)

    @field_validator('rule_id')
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        try:
            uuid.UUID(v, version=4)
            return v
        except ValueError:
            raise ValueError('rule_id must be a valid UUID v4 string')
