"""
The deterministic brain of the SOC Autopilot.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

from engine.deterministic_dedup import AlertCluster
from engine.dry_run_executor import ActionRequest, SimulationResult, simulate_action

class InvestigationState(str, Enum):
    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    INVESTIGATING = "INVESTIGATING"
    WAITING_FOR_EVIDENCE = "WAITING_FOR_EVIDENCE"
    EVALUATING = "EVALUATING"
    READY_FOR_RECOMMENDATION = "READY_FOR_RECOMMENDATION"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETE = "COMPLETE"
    SAFE_STOP = "SAFE_STOP"

class InvestigationBudget(BaseModel):
    max_iterations: int = 3
    max_wall_time_seconds: int = 10
    max_tool_calls: int = 5

class InvestigationContext(BaseModel):
    investigation_id: UUID = Field(default_factory=uuid4)
    cluster: AlertCluster
    state: InvestigationState = InvestigationState.RECEIVED
    budget: InvestigationBudget = Field(default_factory=InvestigationBudget)

    iterations: int = 0
    tool_calls: int = 0
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    hypotheses: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    recommended_action: Optional[ActionRequest] = None
    simulation_result: Optional[SimulationResult] = None

def _mock_llm_proposal(ctx: InvestigationContext) -> dict:
    payload = ctx.cluster.representative_payload
    rule_id = payload.get("rule", {}).get("id", "unknown")
    src_ip = payload.get("src_ip", "unknown")

    if ctx.tool_calls == 0:
        return {
            "action": "request_evidence",
            "hypothesis": f"Analyzing rule {rule_id} from {src_ip}.",
            "tool": "internal_log_search"
        }
    else:
        # Smart Mock LLM: Proposes different actions based on the alert type
        if rule_id == "5710": # Wazuh SSH Brute Force
            target = payload.get("data", {}).get("dstuser") or "attacker_account"
            proposed = ActionRequest(action_type="disable_user", target_id=target, reason="SSH Brute Force confirmed")
        else: # Default to C2 / Block IP
            proposed = ActionRequest(action_type="block_ip", target_id=src_ip, reason="Malicious traffic confirmed")

        return {
            "action": "recommend_action",
            "hypothesis": f"Confirmed malicious activity via rule {rule_id}.",
            "proposed_action": proposed
        }

def run_investigation(cluster: AlertCluster, budget: Optional[InvestigationBudget] = None) -> InvestigationContext:
    ctx = InvestigationContext(cluster=cluster, budget=budget or InvestigationBudget())

    ctx.state = InvestigationState.NORMALIZED
    ctx.state = InvestigationState.INVESTIGATING

    while ctx.state == InvestigationState.INVESTIGATING:
        elapsed = (datetime.now(timezone.utc) - ctx.started_at).total_seconds()
        if (ctx.iterations >= ctx.budget.max_iterations or
            elapsed >= ctx.budget.max_wall_time_seconds or
            ctx.tool_calls >= ctx.budget.max_tool_calls):
            ctx.state = InvestigationState.SAFE_STOP
            break

        ctx.iterations += 1
        proposal = _mock_llm_proposal(ctx)

        if proposal["action"] == "request_evidence":
            ctx.hypotheses.append(proposal["hypothesis"])
            ctx.state = InvestigationState.WAITING_FOR_EVIDENCE
            ctx.evidence.append("Internal logs confirm malicious intent (Mocked).")
            ctx.tool_calls += 1
            ctx.state = InvestigationState.EVALUATING
            ctx.state = InvestigationState.INVESTIGATING

        elif proposal["action"] == "recommend_action":
            ctx.hypotheses.append(proposal["hypothesis"])
            ctx.recommended_action = proposal["proposed_action"]
            ctx.state = InvestigationState.READY_FOR_RECOMMENDATION

    if ctx.state == InvestigationState.READY_FOR_RECOMMENDATION and ctx.recommended_action:
        ctx.simulation_result = simulate_action(ctx.recommended_action)

        if ctx.simulation_result.affected_critical_services > 0:
            ctx.state = InvestigationState.REVIEW_REQUIRED
        else:
            ctx.state = InvestigationState.COMPLETE

    return ctx
