"""
The deterministic brain of the SOC Autopilot.

This module implements a bounded, budgeted investigation loop that consumes
an `AlertCluster`, consults a (mocked) LLM for hypotheses/actions, and
produces a recommended action along with a dry-run simulation result.
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
    """Lifecycle states of an investigation, in roughly chronological order."""

    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    INVESTIGATING = "INVESTIGATING"
    WAITING_FOR_EVIDENCE = "WAITING_FOR_EVIDENCE"
    EVALUATING = "EVALUATING"
    READY_FOR_RECOMMENDATION = "READY_FOR_RECOMMENDATION"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETE = "COMPLETE"
    SAFE_STOP = "SAFE_STOP"


class LLMAction(str, Enum):
    """Actions the (mocked) LLM can propose during an investigation step."""

    REQUEST_EVIDENCE = "request_evidence"
    RECOMMEND_ACTION = "recommend_action"


class LLMProposal(BaseModel):
    """A single proposal returned by the (mocked) LLM for the current step.

    Depending on `action`, either `tool` (for evidence requests) or
    `proposed_action` (for action recommendations) will be populated.
    """

    action: LLMAction
    hypothesis: str
    tool: Optional[str] = None
    proposed_action: Optional[ActionRequest] = None


class InvestigationBudget(BaseModel):
    """Hard limits that bound how much work an investigation may perform."""

    max_iterations: int = 3
    max_wall_time_seconds: int = 10
    max_tool_calls: int = 5


class InvestigationContext(BaseModel):
    """Mutable state accumulated while running a single investigation."""

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


def _generate_mock_llm_proposal(context: InvestigationContext) -> LLMProposal:
    """Produce the next LLM proposal for the given investigation context.

    On the first tool call, the mock always asks for more evidence. On
    subsequent calls, it recommends a concrete containment action based on
    the alert's rule ID.

    Args:
        context: The current investigation state.

    Returns:
        The proposed next step (evidence request or action recommendation).
    """
    payload = context.cluster.representative_payload
    rule_id = payload.get("rule", {}).get("id", "unknown")
    src_ip = payload.get("src_ip", "unknown")

    if context.tool_calls == 0:
        return LLMProposal(
            action=LLMAction.REQUEST_EVIDENCE,
            hypothesis=f"Analyzing rule {rule_id} from {src_ip}.",
            tool="internal_log_search",
        )

    # Smart Mock LLM: Proposes different actions based on the alert type.
    if rule_id == "5710":  # Wazuh SSH Brute Force
        target = payload.get("data", {}).get("dstuser") or "attacker_account"
        proposed_action = ActionRequest(
            action_type="disable_user",
            target_id=target,
            reason="SSH Brute Force confirmed",
        )
    else:  # Default to C2 / Block IP
        proposed_action = ActionRequest(
            action_type="block_ip",
            target_id=src_ip,
            reason="Malicious traffic confirmed",
        )

    return LLMProposal(
        action=LLMAction.RECOMMEND_ACTION,
        hypothesis=f"Confirmed malicious activity via rule {rule_id}.",
        proposed_action=proposed_action,
    )


def run_investigation(
    cluster: AlertCluster, budget: Optional[InvestigationBudget] = None
) -> InvestigationContext:
    """Run a bounded investigation loop over the given alert cluster.

    Repeatedly consults the (mocked) LLM for hypotheses and either gathers
    evidence or produces a recommended action, subject to the iteration,
    wall-time, and tool-call limits defined by `budget`. If a recommendation
    is produced, it is dry-run simulated before the investigation completes.

    Args:
        cluster: The deduplicated alert cluster to investigate.
        budget: Optional override of the default investigation budget.

    Returns:
        The final `InvestigationContext`, including its terminal state,
        any recommended action, and the corresponding simulation result.
    """
    context = InvestigationContext(cluster=cluster, budget=budget or InvestigationBudget())

    context.state = InvestigationState.NORMALIZED
    context.state = InvestigationState.INVESTIGATING

    while context.state == InvestigationState.INVESTIGATING:
        elapsed_seconds = (datetime.now(timezone.utc) - context.started_at).total_seconds()
        budget_exhausted = (
            context.iterations >= context.budget.max_iterations
            or elapsed_seconds >= context.budget.max_wall_time_seconds
            or context.tool_calls >= context.budget.max_tool_calls
        )
        if budget_exhausted:
            context.state = InvestigationState.SAFE_STOP
            break

        context.iterations += 1
        proposal = _generate_mock_llm_proposal(context)

        if proposal.action == LLMAction.REQUEST_EVIDENCE:
            context.hypotheses.append(proposal.hypothesis)
            context.state = InvestigationState.WAITING_FOR_EVIDENCE
            context.evidence.append("Internal logs confirm malicious intent (Mocked).")
            context.tool_calls += 1
            # Evidence gathered synchronously in this mock; transition through
            # EVALUATING and back to INVESTIGATING to loop for the next proposal.
            context.state = InvestigationState.EVALUATING
            context.state = InvestigationState.INVESTIGATING

        elif proposal.action == LLMAction.RECOMMEND_ACTION:
            context.hypotheses.append(proposal.hypothesis)
            context.recommended_action = proposal.proposed_action
            context.state = InvestigationState.READY_FOR_RECOMMENDATION

    if context.state == InvestigationState.READY_FOR_RECOMMENDATION and context.recommended_action:
        context.simulation_result = simulate_action(context.recommended_action)

        if context.simulation_result.affected_critical_services > 0:
            context.state = InvestigationState.REVIEW_REQUIRED
        else:
            context.state = InvestigationState.COMPLETE

    return context
