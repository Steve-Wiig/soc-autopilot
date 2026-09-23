import re

with open("tests/test_e2e_comprehensive.py", "r") as f:
    content = f.read()

# Robust regex to replace the entire test function
pattern = r'def test_e2e_extra_model_fields_rejected\(\):.*?(?=\ndef test_e2e_malicious_enrichment_encapsulated)'

replacement = '''def test_e2e_extra_model_fields_rejected():
    """Proves that Pydantic strict validation rejects extra fields injected by the model."""
    from contracts.slm_recommendation import Classification, Severity, RecommendedAction

    valid_payload = {
        "schema_version": "1.0",
        "classification": Classification.BENIGN,
        "confidence": 0.9,
        "severity": Severity.LOW,
        "recommended_action": RecommendedAction.NO_ACTION,
        "reasoning_summary": "This is a valid reasoning summary.",
        "indicators": [],
        "evidence_refs": [],
        "requires_human_review": False
    }

    # Valid payload should parse
    SLMRawRecommendation.model_validate(valid_payload)

    # Payload with extra injected field should FAIL
    invalid_payload = valid_payload.copy()
    invalid_payload["system_override"] = "BYPASS_POLICY"

    with pytest.raises(Exception):  # Pydantic ValidationError
        SLMRawRecommendation.model_validate(invalid_payload)

'''

content = re.sub(pattern, replacement, content, flags=re.DOTALL)

with open("tests/test_e2e_comprehensive.py", "w") as f:
    f.write(content)

print("✅ test_e2e_extra_model_fields_rejected fixed.")
