"""
Simulates the impact of M1/M2 actions without executing them.

This module provides a dry-run/"what-if" execution layer for security
response actions (e.g. blocking an IP, isolating a host, disabling a user).
It never mutates live systems -- it only returns a deterministic,
predictable estimate of the blast radius and reversibility of an action.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# Type alias for the supported action types. Kept in one place so the
# request model and dispatch table can't drift out of sync.
ActionType = Literal["block_ip", "isolate_host", "disable_user"]


class ActionRequest(BaseModel):
    """A request to simulate the effect of a single response action."""

    action_type: ActionType = Field(
        ..., description="The type of response action to simulate."
    )
    target_id: str = Field(
        ..., description="Identifier of the target (IP, hostname, username, etc.)."
    )
    reason: str = Field(
        ..., description="Human-provided justification for the action."
    )


class SimulationResult(BaseModel):
    """The predicted outcome of simulating an ActionRequest.

    This model never represents a real, executed change -- `live_mutation`
    is always `False` as a hardcoded safety guarantee.
    """

    simulation_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this simulation run.",
    )
    would_execute: bool = Field(
        default=True,
        description="Whether the action would be executed if run for real.",
    )
    live_mutation: bool = Field(
        default=False,
        description="Hardcoded safety guarantee: this is always False.",
    )
    action_type: str = Field(..., description="The action type that was simulated.")
    target_id: str = Field(..., description="The target of the simulated action.")

    # Simulated blast radius
    affected_assets: int = Field(
        default=0, description="Number of assets estimated to be affected."
    )
    affected_critical_services: int = Field(
        default=0,
        description="Number of critical services estimated to be affected.",
    )
    estimated_downtime_minutes: int = Field(
        default=0, description="Estimated downtime, in minutes, caused by the action."
    )

    # Reversibility
    is_reversible: bool = Field(
        default=True, description="Whether the action can be rolled back."
    )
    rollback_plan: str = Field(
        default="N/A", description="Human-readable description of how to roll back."
    )

    constraints: List[str] = Field(
        default_factory=list,
        description="Warnings or requirements that apply to this action.",
    )


def _simulate_block_ip(request: ActionRequest) -> SimulationResult:
    """Simulate blocking an IP address at the edge firewall."""
    return SimulationResult(
        action_type=request.action_type,
        target_id=request.target_id,
        affected_assets=0,  # Edge firewall blocks don't affect internal assets
        affected_critical_services=0,
        is_reversible=True,
        rollback_plan=f"Remove firewall rule for {request.target_id}",
        constraints=["Requires human approval if IP is in internal RFC1918 space"],
    )


def _simulate_isolate_host(request: ActionRequest) -> SimulationResult:
    """Simulate isolating a host by quarantining its network access."""
    return SimulationResult(
        action_type=request.action_type,
        target_id=request.target_id,
        affected_assets=1,
        affected_critical_services=1,  # Mocking a critical service hit
        estimated_downtime_minutes=15,
        is_reversible=True,
        rollback_plan=f"Remove quarantine VLAN tag from {request.target_id}",
        constraints=["Will sever all network access", "Requires Helpdesk notification"],
    )


def _simulate_disable_user(request: ActionRequest) -> SimulationResult:
    """Simulate disabling a user account in the directory service."""
    return SimulationResult(
        action_type=request.action_type,
        target_id=request.target_id,
        affected_assets=0,
        is_reversible=True,
        rollback_plan=f"Re-enable AD account {request.target_id} and force password reset",
        constraints=["Cannot disable Domain Admins"],
    )


# Dispatch table mapping each supported action type to its simulation
# handler. Using a lookup table instead of an if/elif chain keeps this
# extensible and keeps each action's logic isolated and independently
# testable.
_SIMULATORS: Dict[ActionType, Callable[[ActionRequest], SimulationResult]] = {
    "block_ip": _simulate_block_ip,
    "isolate_host": _simulate_isolate_host,
    "disable_user": _simulate_disable_user,
}


def simulate_action(request: ActionRequest) -> SimulationResult:
    """Deterministically simulate the impact of a response action.

    In the future, this will query the CMDB/Asset Graph to compute a real
    blast radius. Today, it provides a safe, predictable mock response for
    each supported action type.

    Args:
        request: The action to simulate.

    Returns:
        A SimulationResult describing the predicted impact and
        reversibility of the action. This never mutates live systems.

    Raises:
        ValueError: If `request.action_type` is not supported.
    """
    simulator = _SIMULATORS.get(request.action_type)
    if simulator is None:
        raise ValueError(f"Unknown action type: {request.action_type}")

    return simulator(request)
