"""
Adversarial tests for the trust boundary.
Proves that external enrichment data is encapsulated as untrusted evidence
and cannot alter system logic, even when it contains prompt injection payloads.
"""
import pytest
from engine.deterministic_enrichment import EnrichmentEngine

def test_keyword_injection_is_encapsulated():
    """Provider returns 'IGNORE ALL PREVIOUS INSTRUCTIONS' - must be encapsulated, not filtered."""
    engine = EnrichmentEngine()
    result = engine.enrich_indicator("10.0.0.5", "IP")
    assert result.provenance.status == "SUCCESS"
    # The injection payload is preserved as evidence, not discarded
    notes_record = next(r for r in result.records if r.field == "notes")
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in notes_record.value
    # And it is explicitly labeled untrusted
    assert notes_record.trust_class == "UNTRUSTED_EXTERNAL"

def test_markdown_injection_is_encapsulated():
    """Provider returns markdown/javascript injection - must be encapsulated."""
    engine = EnrichmentEngine()
    result = engine.enrich_indicator("1.2.3.4", "IP")
    assert result.provenance.status == "SUCCESS"
    desc_record = next(r for r in result.records if r.field == "description")
    assert "javascript:alert" in desc_record.value
    assert desc_record.trust_class == "UNTRUSTED_EXTERNAL"

def test_whois_injection_is_encapsulated():
    """Provider returns whois-based injection - must be encapsulated."""
    engine = EnrichmentEngine()
    result = engine.enrich_indicator("evil.com", "DOMAIN")
    assert result.provenance.status == "SUCCESS"
    whois_record = next(r for r in result.records if r.field == "whois")
    assert "IGNORE PREVIOUS" in whois_record.value
    assert whois_record.trust_class == "UNTRUSTED_EXTERNAL"

def test_clean_enrichment_still_works():
    """Legitimate enrichment still produces valid EvidenceRecords."""
    engine = EnrichmentEngine()
    result = engine.enrich_indicator("192.168.1.100", "IP")
    assert result.provenance.status == "SUCCESS"
    assert len(result.records) == 2  # reputation + country
    for r in result.records:
        assert r.trust_class == "UNTRUSTED_EXTERNAL"
        assert r.source == "mock_ip_provider"
        assert r.indicator == "192.168.1.100"

def test_unsupported_type_returns_empty():
    """Unknown indicator type returns UNSUPPORTED_TYPE status."""
    engine = EnrichmentEngine()
    result = engine.enrich_indicator("foo", "UNKNOWN_TYPE")
    assert result.provenance.status == "UNSUPPORTED_TYPE"
    assert result.records == []

def test_enrich_entities_aggregates():
    """enrich_entities correctly aggregates multiple indicator types."""
    engine = EnrichmentEngine()
    results = engine.enrich_entities({
        "ips": ["192.168.1.100", "10.0.0.5"],
        "domains": ["evil.com"],
        "hashes": ["abc123"],
    })
    assert len(results) == 4
    assert all(r.provenance.status == "SUCCESS" for r in results)

def test_evidence_record_size_bounded():
    """Very long values are truncated to 1000 chars."""
    engine = EnrichmentEngine()
    # Inject a provider that returns a huge value
    engine.providers["IP"] = lambda ip: {"huge": "A" * 5000}
    result = engine.enrich_indicator("9.9.9.9", "IP")
    huge_record = next(r for r in result.records if r.field == "huge")
    assert len(huge_record.value) == 1000
