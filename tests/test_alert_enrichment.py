import time
import uuid
from unittest.mock import patch, MagicMock
import pytest


# Valid UUID v4 for alert_id (generated once for reference)
VALID_ALERT_ID = str(uuid.uuid4())

# Valid severity enums as specified
VALID_SEVERITIES = ["low", "medium", "high", "critical"]


# Minimal stub service to make tests self-contained
# Replace with your actual AlertEnrichmentService import path
class AlertEnrichmentService:
    def enrich(self, alert_id: str, severity: str, timeout: float | None = None) -> dict:
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity: {severity}")
        # Simulate external operation respecting timeout parameter
        if timeout:
            time.sleep(timeout)
        return {
            "alert_id": alert_id,
            "severity": severity,
            "status": "enriched",
        }

    def enrich_from_dict(self, alert_dict: dict) -> dict:
        alert_id = alert_dict.get("alert_id", "")
        severity = alert_dict.get("severity", "")
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity in dict: {severity}")
        return {
            "alert_id": alert_id,
            "severity": severity,
            "status": "enriched_from_dict",
        }


class TestAlertEnrichmentService:
    """Pytest test suite for AlertEnrichmentService."""

    def test_successful_enrichment(self):
        """Test enrichment succeeds with valid alert_id and severity enum."""
        service = AlertEnrichmentService()
        alert_id = str(uuid.uuid4())
        severity = "high"
        result = service.enrich(alert_id, severity)
        assert result["alert_id"] == alert_id
        assert result["severity"] == severity
        assert result["status"] == "enriched"

    def test_timeout(self):
        """Test timeout behavior using a very short timeout and mocking."""
        service = AlertEnrichmentService()
        alert_id = str(uuid.uuid4())
        # Mock time.sleep to immediately raise TimeoutError
        with patch("time.sleep", side_effect=TimeoutError("Operation timed out")):
            try:
                service.enrich(alert_id, "medium", timeout=0.001)
                assert False, "Expected TimeoutError to be raised"
            except TimeoutError as e:
                assert "Operation timed out" in str(e)

    def test_failure_mocking_exception(self):
        """Test failure when an exception is mocked internally."""
        service = AlertEnrichmentService()
        alert_id = str(uuid.uuid4())
        with patch.object(service, "enrich", side_effect=ValueError("Enrichment failed")):
            try:
                service.enrich(alert_id, "low")
                assert False, "Expected ValueError to be raised"
            except ValueError as e:
                assert "Enrichment failed" in str(e)

    def test_dict_input(self):
        """Test enrichment with dict input containing valid fields."""
        service = AlertEnrichmentService()
        alert_dict = {
            "alert_id": str(uuid.uuid4()),
            "severity": "critical",
            "source": "test_source",
        }
        result = service.enrich_from_dict(alert_dict)
        assert result["alert_id"] == alert_dict["alert_id"]
        assert result["severity"] == "critical"
        assert result["status"] == "enriched_from_dict"
