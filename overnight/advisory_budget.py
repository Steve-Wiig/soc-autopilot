from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CandidateFailure(str, Enum):
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    INVALID_JSON = "INVALID_JSON"
    INVALID_PYTHON = "INVALID_PYTHON"
    POLICY_REJECTION = "POLICY_REJECTION"
    TEST_FAILURE = "TEST_FAILURE"
    VACUOUS_TEST = "VACUOUS_TEST"
    REPEATED_PATCH = "REPEATED_PATCH"
    STALE_ADVISORY = "STALE_ADVISORY"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class TerminalState(str, Enum):
    APPLIED = "APPLIED"
    DEFERRED_MODEL_UNRELIABLE = "DEFERRED_MODEL_UNRELIABLE"
    DEFERRED_RATE_LIMIT = "DEFERRED_RATE_LIMIT"
    DEFERRED_PROVIDER_UNAVAILABLE = "DEFERRED_PROVIDER_UNAVAILABLE"
    DEFERRED_STALE = "DEFERRED_STALE"
    DEFERRED_MISSING_PROVENANCE = "DEFERRED_MISSING_PROVENANCE"
    DEFERRED_HUMAN_REVIEW = "DEFERRED_HUMAN_REVIEW"
    REJECTED_POLICY = "REJECTED_POLICY"
    REJECTED_INVALID_PATCH = "REJECTED_INVALID_PATCH"
    REJECTED_VACUOUS_TEST = "REJECTED_VACUOUS_TEST"
    REJECTED_REPEATED_PATCH = "REJECTED_REPEATED_PATCH"


@dataclass(frozen=True)
class BudgetPolicy:
    max_total_model_attempts: int = 5
    max_invalid_patch_attempts: int = 2
    max_empty_responses: int = 1
    max_provider_switches: int = 2


@dataclass
class AdvisoryAttemptState:
    advisory_id: str
    advisory_fingerprint: str
    source_fingerprint: str

    total_attempts: int = 0
    invalid_patch_attempts: int = 0
    empty_response_attempts: int = 0
    provider_switches: int = 0

    last_failure: Optional[CandidateFailure] = None
    last_provider: Optional[str] = None
    last_model: Optional[str] = None
    last_candidate_fingerprint: Optional[str] = None

    failed_candidate_fingerprints: set[str] = field(default_factory=set)

    terminal_state: Optional[TerminalState] = None
    terminal_reason: Optional[str] = None

    def is_terminal(self) -> bool:
        return self.terminal_state is not None


IMMEDIATE_TERMINAL = {
    CandidateFailure.POLICY_REJECTION: TerminalState.REJECTED_POLICY,
    CandidateFailure.REPEATED_PATCH: TerminalState.REJECTED_REPEATED_PATCH,
    CandidateFailure.STALE_ADVISORY: TerminalState.DEFERRED_STALE,
    CandidateFailure.MISSING_PROVENANCE: TerminalState.DEFERRED_MISSING_PROVENANCE,
    CandidateFailure.VACUOUS_TEST: TerminalState.REJECTED_VACUOUS_TEST,
}


def should_continue(state: AdvisoryAttemptState, policy: BudgetPolicy) -> bool:
    if state.is_terminal():
        return False
    if state.total_attempts >= policy.max_total_model_attempts:
        return False
    if state.invalid_patch_attempts >= policy.max_invalid_patch_attempts:
        return False
    if state.empty_response_attempts > policy.max_empty_responses:
        return False
    if state.provider_switches > policy.max_provider_switches:
        return False
    return True


def terminate(
    state: AdvisoryAttemptState,
    terminal_state: TerminalState,
    reason: str,
) -> None:
    if state.is_terminal():
        return
    state.terminal_state = terminal_state
    state.terminal_reason = reason


def begin_model_attempt(state: AdvisoryAttemptState) -> None:
    if state.is_terminal():
        raise RuntimeError("attempt after terminal state")
    state.total_attempts += 1


def terminal_for_budget_exhaustion(
    state: AdvisoryAttemptState,
) -> TerminalState:
    failure = state.last_failure

    if failure is None:
        return TerminalState.DEFERRED_MODEL_UNRELIABLE

    if failure == CandidateFailure.RATE_LIMIT:
        return TerminalState.DEFERRED_RATE_LIMIT

    if failure in (
        CandidateFailure.PROVIDER_UNAVAILABLE,
        CandidateFailure.TIMEOUT,
    ):
        return TerminalState.DEFERRED_PROVIDER_UNAVAILABLE

    if failure in IMMEDIATE_TERMINAL:
        return IMMEDIATE_TERMINAL[failure]

    return TerminalState.DEFERRED_MODEL_UNRELIABLE


def record_failure(
    state: AdvisoryAttemptState,
    policy: BudgetPolicy,
    failure: CandidateFailure,
) -> None:
    state.last_failure = failure

    if failure in IMMEDIATE_TERMINAL:
        terminate(
            state,
            IMMEDIATE_TERMINAL[failure],
            f"terminal failure: {failure.value}",
        )
        return

    if failure == CandidateFailure.INVALID_PYTHON:
        state.invalid_patch_attempts += 1
    elif failure == CandidateFailure.TEST_FAILURE:
        state.invalid_patch_attempts += 1
    elif failure == CandidateFailure.EMPTY_RESPONSE:
        state.empty_response_attempts += 1

    if not should_continue(state, policy):
        terminate(
            state,
            terminal_for_budget_exhaustion(state),
            "advisory budget exhausted",
        )
