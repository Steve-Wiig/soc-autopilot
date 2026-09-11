from datetime import datetime, timezone
from enum import Enum
from typing import List
from pydantic import BaseModel, Field, field_validator, ConfigDict

class Classification(str, Enum):
    BENIGN = "BENIGN"
    SUSPICIOUS = "SUSPICIOUS"
    MALICIOUS = "MALICIOUS"
    UNKNOWN = "UNKNOWN"

class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class RecommendedAction(str, Enum):
    NO_ACTION = "NO_ACTION"
    ENRICH = "ENRICH"
    ESCALATE = "ESCALATE"
    ISOLATE = "ISOLATE"
    BLOCK = "BLOCK"
    OTHER = "OTHER"

EXPECTED_SCHEMA_VERSION = "1.0"

class SLMRawRecommendation(BaseModel):
    schema_version: str = Field(default=EXPECTED_SCHEMA_VERSION)
    classification: Classification
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity
    recommended_action: RecommendedAction
    reasoning_summary: str = Field(min_length=10, max_length=2000)
    indicators: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    requires_human_review: bool

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator('schema_version')
    @classmethod
    def check_schema_version(cls, v: str) -> str:
        if v != EXPECTED_SCHEMA_VERSION:
            raise ValueError(f"Invalid schema_version: expected '{EXPECTED_SCHEMA_VERSION}', got '{v}'")
        return v

    @field_validator('indicators', 'evidence_refs')
    @classmethod
    def deduplicate_and_strip(cls, v: List[str]) -> List[str]:
        return list(dict.fromkeys(item.strip() for item in v if item.strip()))

class RecommendationEnvelope(BaseModel):
    recommendation_id: str
    event_id: str
    envelope_schema_version: str = Field(default="1.0")
    recommendation_schema_version: str
    model_id: str
    model_version: str
    raw_output_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recommendation: SLMRawRecommendation

class ContractViolationError(Exception):
    def __init__(self, message: str, raw_output_hash: str, violation_details: str):
        super().__init__(message)
        self.raw_output_hash = raw_output_hash
        self.violation_details = violation_details

class LocalModelUnavailableError(Exception):
    pass
