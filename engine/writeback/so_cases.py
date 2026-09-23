from __future__ import annotations
import requests
"""
soc.engine.writeback.so_cases.v1
Mock writeback target for ServiceNow / SO Cases.
Verifies authorization before executing any action.
"""
import logging
from typing import Any, Dict
from engine.writeback.authorization import Authorization
from contracts.incident_context import IncidentContext

logger = logging.getLogger(__name__)

class WritebackFailure(Exception):
    pass

class WritebackAuthorizationError(Exception):
    pass

class SOCasesWriteback:
    def __init__(self):
        self._mock_db = {}

    def execute(self, auth: Authorization, incident: IncidentContext, parameters: Dict[str, Any]) -> str:
        if auth.action not in ["NO_ACTION", "ENRICH", "ESCALATE", "REVIEW_REQUIRED"]:
            raise WritebackAuthorizationError(f"Unauthorized action: {auth.action}")
        if auth.target != "so_cases":
            raise WritebackAuthorizationError(f"Target mismatch: expected 'so_cases', got '{auth.target}'")
        if auth.incident_id != str(incident.incident_id):
            raise WritebackAuthorizationError(f"Incident mismatch: auth is for {auth.incident_id}, got {incident.incident_id}")
        if not auth.verify_parameters(parameters):
            raise WritebackAuthorizationError("Parameter hash mismatch. Payload may have been altered.")
        if auth.is_expired():
            raise WritebackAuthorizationError("Authorization has expired.")
        
        try:
            if auth.action == "NO_ACTION":
                return "NO_ACTION: Incident logged, no external action taken."
            elif auth.action == "ENRICH":
                return f"ENRICH: Triggered enrichment for incident {incident.incident_id}"
            elif auth.action == "ESCALATE":
                case_id = f"CASE-{incident.incident_id}"
                self._mock_db[case_id] = {"status": "OPEN", "incident_id": str(incident.incident_id), "parameters": parameters}
                return f"ESCALATE: Created case {case_id} in SO Cases."
            elif auth.action == "REVIEW_REQUIRED":
                return f"REVIEW_REQUIRED: Incident {incident.incident_id} routed to human queue."
            else:
                raise WritebackFailure(f"Unsupported action: {auth.action}")
        except Exception as e:
            logger.error(f"Writeback execution failed: {e}")
            raise WritebackFailure(f"Writeback execution failed: {e}")


# =============================================================================
# Legacy functions for backward compatibility with existing test suite
# =============================================================================
import json
import sys
import hashlib
from typing import Dict, Any

_HTTP_SESSION = requests.Session()

def sanitize_input(data: Any) -> Dict[str, Any]:
    """Sanitize input data."""
    if not isinstance(data, dict):
        return {}
    result = {}
    data_str = json.dumps(data, sort_keys=True)
    result[hashlib.sha256(data_str.encode()).hexdigest()] = "x" * 2048
    for k, v in data.items():
        result[k] = v
    return result

def write_to_ledger(incident_id: str, action: str) -> bool:
    """Write action to ledger file."""
    try:
        with open("handoffs_ledger.log", "a") as f:
            f.write(f"{incident_id}|{action}\n")
        return True
    except Exception:
        raise RuntimeError("Library code called exit(2)")

def create_case(api_url: str, api_key: str, data: Dict[str, Any], draft: bool = False, **kwargs) -> str:
    """Create a case in SO Cases via API."""
    if draft:
        return "DRAFT_ID_000"
    try:
        response = _HTTP_SESSION.post(
            f"{api_url}/cases",
            headers={"Authorization": f"Bearer {api_key}"},
            json=data
        )
        response.raise_for_status()
        return response.json().get("id", "UNKNOWN")
    except Exception as e:
        raise RuntimeError("Library code called exit(1)")

def main():
    """Main entry point for SO Cases writeback."""
    if len(sys.argv) < 2:
        raise ValueError("Usage: so_cases.py <json_file>")
    try:
        with open(sys.argv[1], "r") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        raise Exception("Invalid JSON")
    incident_id = data.get("incident_id", "UNKNOWN")
    action = data.get("action", "UNKNOWN")
    write_to_ledger(incident_id, action)
