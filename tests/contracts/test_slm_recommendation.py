import pytest
import json
from contracts.slm_recommendation import SLMRawRecommendation, RecommendationEnvelope, EXPECTED_SCHEMA_VERSION, Classification

VALID_PAYLOAD = {
    "schema_version": EXPECTED_SCHEMA_VERSION, "classification": "SUSPICIOUS", "confidence": 0.85,
    "severity": "MEDIUM", "recommended_action": "ENRICH",
    "reasoning_summary": "Observed anomalous PowerShell execution with encoded arguments.",
    "indicators": ["powershell.exe", "-enc"], "evidence_refs": ["wazuh:alert:12345"], "requires_human_review": True
}

def test_valid_contract_parses_successfully():
    rec = SLMRawRecommendation.model_validate_json(json.dumps(VALID_PAYLOAD))
    assert rec.classification == Classification.SUSPICIOUS

def test_strict_mode_rejects_string_confidence():
    payload = VALID_PAYLOAD.copy()
    payload["confidence"] = "0.85"
    with pytest.raises(Exception):
        SLMRawRecommendation.model_validate_json(json.dumps(payload))

def test_extra_fields_are_forbidden():
    payload = VALID_PAYLOAD.copy()
    payload["hallucinated_field"] = "malicious_script.ps1"
    with pytest.raises(Exception):
        SLMRawRecommendation.model_validate_json(json.dumps(payload))

def test_missing_required_field_fails():
    payload = VALID_PAYLOAD.copy()
    del payload["severity"]
    with pytest.raises(Exception):
        SLMRawRecommendation.model_validate_json(json.dumps(payload))

def test_invalid_enum_value_fails():
    payload = VALID_PAYLOAD.copy()
    payload["severity"] = "EXTREME"
    with pytest.raises(Exception):
        SLMRawRecommendation.model_validate_json(json.dumps(payload))

def test_markdown_fences_stripped_before_validation():
    raw_llm_output = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
    cleaned = raw_llm_output.strip().removeprefix("```json").removesuffix("```").strip()
    rec = SLMRawRecommendation.model_validate_json(cleaned)
    assert rec.classification == Classification.SUSPICIOUS
