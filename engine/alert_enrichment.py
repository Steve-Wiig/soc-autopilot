import concurrent.futures
import time
from typing import Union, Any


class Alert:
    """Represents a raw alert from the monitoring system."""
    def __init__(self, alert_id: str, message: str, **kwargs: Any):
        self.alert_id = alert_id
        self.message = message
        self.metadata = kwargs

    def __repr__(self) -> str:
        return f"Alert(id={self.alert_id!r}, message={self.message!r})"


class EnrichedAlert:
    """Represents an alert enriched with LLM-generated insights."""
    def __init__(self, alert: Alert, insights: str):
        self.alert = alert
        self.insights = insights

    def __repr__(self) -> str:
        return f"EnrichedAlert(alert={self.alert!r}, insights={self.insights!r})"


class AlertEnrichmentService:
    """Service that simulates enriching an alert via an LLM call in a separate thread."""

    def _simulate_llm_call(self, alert: Alert) -> EnrichedAlert:
        """Simulate an LLM call that may take variable time."""
        # Sleep for 5 seconds to simulate normal LLM latency.
        # Change to > 30 to test timeout behavior.
        time.sleep(5)
        # Simulate a successful LLM response
        return EnrichedAlert(alert=alert, insights="Simulated LLM insight: consider scaling resources.")

    def enrich_alert(self, alert: Union[Alert, dict]) -> Union[EnrichedAlert, Alert]:
        # Normalize dict to Alert if needed
        if isinstance(alert, dict):
            alert = Alert(**alert)

        # Run the simulated LLM call in a thread pool with a 30-second timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._simulate_llm_call, alert)
            try:
                enriched = future.result(timeout=30)
                return enriched
            except concurrent.futures.TimeoutError:
                # 30-second timeout reached, return original alert
                return alert
            except Exception:
                # Any exception during the LLM simulation, return original alert
                return alert
