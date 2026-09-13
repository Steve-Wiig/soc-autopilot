"""Tests for _has_high_risk_routing_signal: word boundaries and severity gating."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from overnight.self_improver import (
    _ALWAYS_HIGH_RISK,
    _SEVERITY_GATED_HIGH_RISK,
    _has_high_risk_routing_signal,
    _classify_issue_for_routing,
)


def _issue(description, severity="low", category="maintainability"):
    return {"description": description, "severity": severity, "category": category}


# --- always high risk ------------------------------------------------------

@pytest.mark.parametrize("term", _ALWAYS_HIGH_RISK)
@pytest.mark.parametrize("sev", ["low", "informational", "medium", "high", "critical"])
def test_always_high_risk_terms_trigger_at_any_severity(term, sev):
    issue = _issue(f"the code has a {term} in the handler", severity=sev)
    assert _has_high_risk_routing_signal(issue) is True


# --- severity gating -------------------------------------------------------

@pytest.mark.parametrize("term", _SEVERITY_GATED_HIGH_RISK)
@pytest.mark.parametrize("sev", ["low", "informational"])
def test_severity_gated_terms_do_not_trigger_below_medium(term, sev):
    issue = _issue(f"the code has a {term} in the handler", severity=sev)
    assert _has_high_risk_routing_signal(issue) is False


@pytest.mark.parametrize("term", _SEVERITY_GATED_HIGH_RISK)
@pytest.mark.parametrize("sev", ["medium", "high", "critical"])
def test_severity_gated_terms_trigger_at_medium_and_above(term, sev):
    issue = _issue(f"the code has a {term} in the handler", severity=sev)
    assert _has_high_risk_routing_signal(issue) is True


# --- word boundaries -------------------------------------------------------

def test_audit_inside_identifier_does_not_trigger():
    # audit_chain is a table name; underscore is a word character so \baudit\b
    # does not match it. Severity is set to low, matching the actual
    # mr-192950d0f6 queue item, so the severity-gated "schema" term also
    # does not fire. This is the actual false positive from the queue.
    issue = _issue(
        "insert_chain_links hardcodes column names in the INSERT query. "
        "If audit_chain schema changes (column added/removed), this will "
        "fail at runtime with no compile-time check.",
        severity="low",
    )
    assert _has_high_risk_routing_signal(issue) is False


def test_audit_chain_alone_does_not_trigger_at_high_severity():
    # Pure word-boundary test: audit_chain is an identifier, and no
    # standalone severity-gated term is present, so severity is irrelevant.
    issue = _issue(
        "audit_chain lookups are O(N) per call.",
        severity="high",
    )
    assert _has_high_risk_routing_signal(issue) is False


def test_reauthentication_does_not_trigger():
    issue = _issue("the reauthentication helper should be extracted", severity="high")
    assert _has_high_risk_routing_signal(issue) is False


def test_schema_inside_identifier_does_not_trigger():
    issue = _issue("hardcoded schema_column_order in the query", severity="high")
    assert _has_high_risk_routing_signal(issue) is False


def test_audit_as_standalone_word_at_high_severity_triggers():
    issue = _issue("audit log entries are not written on failure", severity="high")
    assert _has_high_risk_routing_signal(issue) is True


def test_schema_as_standalone_word_at_low_severity_does_not_trigger():
    issue = _issue("hardcoded schema column names in the query", severity="low")
    assert _has_high_risk_routing_signal(issue) is False


def test_sql_injection_at_low_severity_triggers():
    issue = _issue("potential sql injection via unescaped user input", severity="low")
    assert _has_high_risk_routing_signal(issue) is True


# --- classification integration --------------------------------------------

def test_audit_chain_advisory_routes_to_local_tdd():
    # Full reproduction of the mr-192950d0f6 false positive.
    issue = {
        "description": (
            "insert_chain_links hardcodes column names in the INSERT query. "
            "If audit_chain schema changes (column added/removed), this will "
            "fail at runtime with no compile-time check."
        ),
        "category": "maintainability",
        "severity": "low",
        "effort": "small",
        "impact": "low",
    }
    assert _has_high_risk_routing_signal(issue) is False
    assert _classify_issue_for_routing(issue) == "LOCAL_TDD"


def test_real_sql_injection_advisory_routes_to_review():
    issue = {
        "description": "user input is concatenated into a raw sql injection-prone query",
        "category": "maintainability",
        "severity": "low",
        "effort": "small",
        "impact": "low",
    }
    assert _has_high_risk_routing_signal(issue) is True
    assert _classify_issue_for_routing(issue) == "REVIEW"


# --- tuple sanity ----------------------------------------------------------

def test_tuples_are_disjoint():
    overlap = set(_ALWAYS_HIGH_RISK) & set(_SEVERITY_GATED_HIGH_RISK)
    assert overlap == set(), f"tuples overlap: {overlap}"


def test_no_empty_or_whitespace_terms():
    for term in _ALWAYS_HIGH_RISK + _SEVERITY_GATED_HIGH_RISK:
        assert term == term.strip() and term, f"bad term: {term!r}"
