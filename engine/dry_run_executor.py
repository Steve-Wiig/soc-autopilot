"""
Simulates the impact of M1/M2 actions without executing them.
"""
from __future__ import annotations

from typing import Literal, List, Optional
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

class ActionRequest(BaseModel):
    action_type: Literal["block_ip", "isolate_host", "disable_user"]
    target_id: str
    reason: str

class SimulationResult(BaseModel):
    simulation_id: UUID = Field(default_factory=uuid4)
    would_execute: bool = True
    live_mutation: bool = False  # Hardcoded safety guarantee
    action_type: str
    target_id: str

    # Simulated blast radius
    affected_assets: int = 0
    affected_critical_services: int = 0
    estimated_downtime_minutes: int = 0

    # Reversibility
    is_reversible: bool = True
    rollback_plan: str = "N/A"

    constraints: List[str] = Field(default_factory=list)

def simulate_action(request: ActionRequest) -> SimulationResult:
    """
    Deterministic simulation. In the future, this queries the CMDB/Asset Graph.
    Today, it provides a safe, predictable mock response.
    """

    if request.action_type == "block_ip":
        return SimulationResult(
            action_type=request.action_type,
            target_id=request.target_id,
            affected_assets=0, # Edge firewall blocks don't affect internal assets
            affected_critical_services=0,
            is_reversible=True,
            rollback_plan=f"Remove firewall rule for {request.target_id}",
            constraints=["Requires human approval if IP is in internal RFC1918 space"]
        )

    elif request.action_type == "isolate_host":
        return SimulationResult(
            action_type=request.action_type,
            target_id=request.target_id,
            affected_assets=1,
            affected_critical_services=1, # Mocking a critical service hit
            estimated_downtime_minutes=15,
            is_reversible=True,
            rollback_plan=f"Remove quarantine VLAN tag from {request.target_id}",
            constraints=["Will sever all network access", "Requires Helpdesk notification"]
        )

    elif request.action_type == "disable_user":
        return SimulationResult(
            action_type=request.action_type,
            target_id=request.target_id,
            affected_assets=0,
            is_reversible=True,
            rollback_plan=f"Re-enable AD account {request.target_id} and force password reset",
            constraints=["Cannot disable Domain Admins"]
        )

    raise ValueError(f"Unknown action type: {request.action_type}")
