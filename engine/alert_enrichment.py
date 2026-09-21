"""Alert enrichment service.

Provides data classes for raw and enriched alerts, along with a service
that simulates enriching an alert via an LLM call executed in a background
thread, subject to a timeout.
"""

import concurrent.futures
import time
from typing import Any, Dict, Union

# Simulated latency (in seconds) for the mocked LLM call.
# Set higher than SIMULATED_LLM_CALL_TIMEOUT_SECONDS to test timeout behavior.
SIMULATED_LLM_CALL_DURATION_SECONDS = 5

# Maximum time (in seconds) to wait for the LLM call before giving up
# and returning the original, unenriched alert.
SIMULATED_LLM_CALL_TIMEOUT_SECONDS = 30


class Alert:
    """Represents a raw alert from the monitoring system."""

    def __init__(self, alert_id: str, message: str, **metadata: Any) -> None:
        """Initialize an Alert.

        Args:
            alert_id: Unique identifier for the alert.
            message: Human-readable alert message.
            **metadata: Additional arbitrary alert metadata.
        """
        self.alert_id = alert_id
        self.message = message
        self.metadata: Dict[str, Any] = metadata

    def __repr__(self) -> str:
        return f"Alert(id={self.alert_id!r}, message={self.message!r})"


class EnrichedAlert:
    """Represents an alert enriched with LLM-generated insights."""

    def __init__(self, alert: Alert, insights: str) -> None:
        """Initialize an EnrichedAlert.

        Args:
            alert: The original alert that was enriched.
            insights: Insights generated for the alert (e.g., by an LLM).
        """
        self.alert = alert
        self.insights = insights

    def __repr__(self) -> str:
        return f"EnrichedAlert(alert={self.alert!r}, insights={self.insights!r})"


class AlertEnrichmentService:
    """Service that enriches alerts using a simulated LLM call.

    The simulated LLM call runs in a separate thread so that a slow or
    hanging call can be bounded by a timeout. If the call does not
    complete within the timeout, or raises an exception, the original
    alert is returned unmodified.
    """

    def _simulate_llm_call(self, alert: Alert) -> EnrichedAlert:
        """Simulate an LLM call that enriches an alert with insights.

        Args:
            alert: The alert to enrich.

        Returns:
            An EnrichedAlert containing the original alert and simulated
            insights.
        """
        # Simulate variable LLM latency.
        time.sleep(SIMULATED_LLM_CALL_DURATION_SECONDS)
        # Simulate a successful LLM response.
        return EnrichedAlert(
            alert=alert,
            insights="Simulated LLM insight: consider scaling resources.",
        )

    def enrich_alert(self, alert: Union[Alert, Dict[str, Any]]) -> Union[EnrichedAlert, Alert]:
        """Enrich an alert with LLM-generated insights.

        Runs the simulated LLM call in a background thread with a bounded
        timeout. If the call times out or raises an exception, the
        original alert is returned instead of an EnrichedAlert.

        Args:
            alert: The alert to enrich, either as an Alert instance or a
                dict of keyword arguments accepted by Alert's constructor.

        Returns:
            An EnrichedAlert on success, or the original Alert if the
            enrichment call timed out or failed.
        """
        # Normalize dict input to an Alert instance if needed.
        if isinstance(alert, dict):
            alert = Alert(**alert)

        # Run the simulated LLM call in a thread pool with a timeout.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._simulate_llm_call, alert)
            try:
                return future.result(timeout=SIMULATED_LLM_CALL_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                # Timeout reached; return the original, unenriched alert.
                return alert
            except Exception:
                # Any failure during the simulated LLM call; return the
                # original, unenriched alert.
                return alert
