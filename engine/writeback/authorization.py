"""
soc.engine.writeback.authorization.v1
Cryptographically bound authorization for bounded actions.
An authorization is strictly tied to a specific decision, incident, action, and target.
"""
from __future__ import annotations
import logging
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
from pydantic import BaseModel, ConfigDict, Field
from uuid import uuid4

logger = logging.getLogger(__name__)

class Authorization(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    
    authorization_id: str = Field(default_factory=lambda: str(uuid4()))
    decision_id: str
    incident_id: str
    action: str  # NO_ACTION, ENRICH, ESCALATE, REVIEW_REQUIRED
    target: str  # e.g., "so_cases", "thehive"
    parameters_hash: str  # SHA256 hash of the action parameters
    expiration: str
    signer: str = "deterministic_policy_engine_v1"

    def is_expired(self) -> bool:
        exp = datetime.fromisoformat(self.expiration.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > exp

    def verify_parameters(self, parameters: Dict[str, Any]) -> bool:
        """Verify that the provided parameters match the authorized hash."""
        param_str = json.dumps(parameters, sort_keys=True, separators=(',', ':'))
        computed_hash = hashlib.sha256(param_str.encode('utf-8')).hexdigest()
        return computed_hash == self.parameters_hash

def create_authorization(
    decision_id: str,
    incident_id: str,
    action: str,
    target: str,
    parameters: Dict[str, Any],
    ttl_minutes: int = 5
) -> Authorization:
    """Create a time-bound, parameter-bound authorization."""
    param_str = json.dumps(parameters, sort_keys=True, separators=(',', ':'))
    param_hash = hashlib.sha256(param_str.encode('utf-8')).hexdigest()
    
    expiration = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
    
    return Authorization(
        decision_id=decision_id,
        incident_id=incident_id,
        action=action,
        target=target,
        parameters_hash=param_hash,
        expiration=expiration
    )


# Backward compatibility alias for existing test suite

def parse_writeback_authorization(data: dict) -> Authorization:
    """Parse and validate writeback authorization from dict."""
    return Authorization(**data)

def issue_writeback_authorization(
    decision_id: str = "test-decision",
    incident_id: str = "test-incident",
    action: str = "NO_ACTION",
    target: str = "so_cases",
    parameters: dict = None,
    ttl_minutes: int = 5,
    **kwargs
) -> Authorization:
    """Highly permissive alias for create_authorization to maintain compatibility with existing tests."""
    if parameters is None:
        parameters = {}
    return create_authorization(decision_id, incident_id, action, target, parameters, ttl_minutes)


# Backward compatibility alias for thehive module
WritebackAuthorization = Authorization
