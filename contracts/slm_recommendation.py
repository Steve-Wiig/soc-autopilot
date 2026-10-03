// """Data contracts for Small Language Model (SLM) security recommendations.

This module defines the schema for recommendations produced by an SLM when
analyzing security events, along with the envelope used to transport those
recommendations, and the errors raised when a recommendation violates the
expected contract or when the local model is unavailable.

from datetime import datetime, timezone
from enum import Enum
from typing import Final, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator, ConfigDict


class Classification(str, Enum):
    """Possible classifications an SLM can assign to a security event."""

    BENIGN = "BENIGN"
    SUSPICIOUS = "SUSPICIOUS"
    MALICIOUS = "MALICIOUS"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    """Severity levels associated with a classified security event."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecommendedAction(str, Enum):
    """Actions an SLM can recommend in response to a security event."""

    NO_ACTION = "NO_ACTION"
    ENRICH = "ENRICH"
    ESCALATE = "ESCALATE"
    ISOLATE = "ISOLATE"
    BLOCK = "BLOCK"
    OTHER = "OTHER"


EXPECTED_SCHEMA_VERSION: Final[str] = "1.0"
"""The only recommendation schema version currently accepted by this contract."""


class SLMRawRecommendation(BaseModel):
    """The raw recommendation payload produced directly by an SLM.

    This model enforces strict validation (no extra fields, strict type
    coercion) since it represents untrusted output from a model that must
    conform exactly to the expected contract before being trusted downstream.
    """

    schema_version: str = Field(
        default=EXPECTED_SCHEMA_VERSION,
        description="Version of the recommendation schema being used.",
    )
    classification: Classification = Field(
        description="The classification assigned to the analyzed event."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model's confidence in the classification, between 0 and 1.",
    )
    severity: Severity = Field(
        description="Severity level associated with the classification."
    )
    recommended_action: RecommendedAction = Field(
        description="Action recommended by the model in response to the event."
    )
    reasoning_summary: str = Field(
        min_length=10,
        max_length=2000,
        description="Human-readable summary explaining the model's reasoning.",
    )
    indicators: List[str] = Field(
        default_factory=list,
        description="List of indicators (e.g. IOCs) supporting the recommendation.",
    )
    evidence_refs: List[str] = Field(
        default_factory=list,
        description="References to evidence supporting the recommendation.",
    )
    requires_human_review: bool = Field(
        description="Whether this recommendation requires human review before acting."
    )

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator('schema_version')
    @classmethod
    def check_schema_version(cls, value: str) -> str:
        """Ensure the schema_version matches the version this contract supports."""
        if value != EXPECTED_SCHEMA_VERSION:
            raise ValueError(
                f"Invalid schema_version: expected '{EXPECTED_SCHEMA_VERSION}', got '{value}'"
            )
        return value

    @field_validator('indicators', 'evidence_refs')
    @classmethod
    def deduplicate_and_strip(cls, value: List[str]) -> List[str]:
        """Strip whitespace, drop empty entries, and remove duplicates while
        preserving the original order.
        """
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class RecommendationEnvelope(BaseModel):
    """Transport envelope wrapping an SLM recommendation with metadata.

    Carries identifying and provenance information (recommendation/event ids,
    model identity, raw output hash, timestamps) alongside the validated
    recommendation payload itself.
    """

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
    """Raised when an SLM's raw output fails to satisfy the recommendation contract."""

    def __init__(self, message: str, raw_output_hash: str, violation_details: str) -> None:
        """Initialize the error with context about the violating output.

        Args:
            message: Human-readable description of the violation.
            raw_output_hash: Hash of the raw model output that failed validation.
            violation_details: Detailed information about what failed and why.
        """
        super().__init__(message)
        self.raw_output_hash = raw_output_hash
        self.violation_details = violation_details


class LocalModelUnavailableError(Exception):
    """Raised when the local SLM cannot be reached or fails to respond."""


# --- Validation error codes ---


class ValidationErrorCode:
    """Standardized error codes returned by validate_and_normalize."""

    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    PARSE_FAILURE = "PARSE_FAILURE"
    MISSING_FIELD = "MISSING_FIELD"


# --- Validation adapter ---


def validate_and_normalize(raw_input) -> Tuple[bool, Optional[SLMRawRecommendation], Optional[str]]:
    """
    Adapter function to strip whitespace, coerce types leniently, and map loose inputs
    to the strict SLMRawRecommendation Pydantic model.

    Args:
        raw_input: A string (JSON), dict, or SLMRawRecommendation instance.

    Returns:
        (is_valid: bool, cleaned_data: Optional[SLMRawRecommendation], error_code: Optional[str])
    """
    if raw_input is None:
        return False, None, ValidationErrorCode.PARSE_FAILURE.value

    if isinstance(raw_input, SLMRawRecommendation):
        return True, raw_input, None

    # Parse input into a dict
    if isinstance(raw_input, str):
        try:
            raw_dict = json.loads(raw_input)
        except json.JSONDecodeError:
            return False, None, ValidationErrorCode.PARSE_FAILURE.value
    elif isinstance(raw_input, dict):
        raw_dict = raw_input
    else:
        return False, None, ValidationErrorCode.TYPE_MISMATCH.value

    # Recursively strip whitespace from string values
    def strip_strings(obj):
        if isinstance(obj, dict):
            return {k: strip_strings(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [strip_strings(item) for item in obj]
        elif isinstance(obj, str):
            return obj.strip()
        return obj

    raw_dict = strip_strings(raw_dict)

    # Ensure schema_version defaults if missing, to avoid immediate validation error
    if 'schema_version' not in raw_dict:
        raw_dict['schema_version'] = EXPECTED_SCHEMA_VERSION

    # Attempt Pydantic validation
    try:
        cleaned = SLMRawRecommendation(**raw_dict)
        return True, cleaned, None
    except Exception as e:
        error_msg = str(e)
        if 'schema_version' in error_msg.lower():
            return False, None, ValidationErrorCode.SCHEMA_DRIFT.value
        elif 'missing' in error_msg.lower() or 'required' in error_msg.lower():
            return False, None, ValidationErrorCode.MISSING_FIELD.value
        else:
            return False, None, ValidationErrorCode.TYPE_MISMATCH.value
