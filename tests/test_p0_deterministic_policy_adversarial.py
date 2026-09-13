"""
P0 adversarial tests for the deterministic authorization boundary.

Contract:
  model recommendation != authorization
  model recommendation != provenance
  destructive action != autonomous ALLOW
  untrusted source != autonomous ALLOW
  unknown action = DENY
  human review request = REVIEW
"""
import pytest

from engine.deterministic_policy import (
    RecommendationEnvelope as PolicyRecommendationEnvelope,
    evaluate_deterministic_policy,
)


def _rec(action, severity="LOW", human=False, event_id="EVT-1"):
    return PolicyRecommendationEnvelope(
        recommended_action=action,
        severity=severity,
        requires_human_review=human,
        event_id=event_id,
    )


# --- Destructive actions are never ALLOW, even with trusted runtime ---

@pytest.mark.parametrize("severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
@pytest.mark.parametrize("action", ["BLOCK", "ISOLATE"])
def test_destructive_action_never_allow_with_trust(action, severity):
    out = evaluate_deterministic_policy(
        _rec(action, severity=severity),
        authoritative_trusted_source=True,
    )
    assert out == "REVIEW", f"{severity}+{action} must not ALLOW"


@pytest.mark.parametrize("severity", ["LOW", "MEDIUM"])
def test_escalate_is_review_even_trusted(severity):
    out = evaluate_deterministic_policy(
        _rec("ESCALATE", severity=severity),
        authoritative_trusted_source=True,
    )
    assert out == "REVIEW"


def test_other_is_review_even_trusted():
    out = evaluate_deterministic_policy(
        _rec("OTHER", severity="LOW"),
        authoritative_trusted_source=True,
    )
    assert out == "REVIEW"


# --- Safe actions require authoritative runtime trust ---

@pytest.mark.parametrize("action", ["NO_ACTION", "ENRICH"])
def test_safe_action_allow_only_with_trust(action):
    assert evaluate_deterministic_policy(
        _rec(action, severity="LOW"),
        authoritative_trusted_source=True,
    ) == "ALLOW"

    assert evaluate_deterministic_policy(
        _rec(action, severity="LOW"),
        authoritative_trusted_source=False,
    ) == "REVIEW"


# --- Model cannot manufacture trust ---

def test_model_cannot_manufacture_trust_via_action_or_severity():
    # The adapter passes only action/severity/human/event_id.
    # There is no trust field. Model-authored "trust" cannot influence this.
    out = evaluate_deterministic_policy(
        _rec("BLOCK", severity="LOW", human=False),
        authoritative_trusted_source=False,
    )
    assert out != "ALLOW"


# --- Human review always wins ---

@pytest.mark.parametrize(
    "action",
    ["NO_ACTION", "ENRICH", "ESCALATE", "ISOLATE", "BLOCK", "OTHER"],
)
@pytest.mark.parametrize("trusted", [True, False])
def test_human_review_always_wins(action, trusted):
    out = evaluate_deterministic_policy(
        _rec(action, severity="LOW", human=True),
        authoritative_trusted_source=trusted,
    )
    assert out == "REVIEW"


# --- Unknown action fails closed ---

@pytest.mark.parametrize(
    "action", ["UNKNOWN", "ALLOW", "NO_OP", "DELETE", "", "none", "block "]
)
def test_unknown_action_denies(action):
    out = evaluate_deterministic_policy(
        _rec(action, severity="LOW", human=False),
        authoritative_trusted_source=True,
    )
    assert out == "DENY", f"unknown action {action!r} must DENY"


# --- Severity band is LOW only ---

def test_severity_band_is_low_only():
    """P0: auto-allow is restricted to LOW severity only.

    MEDIUM, HIGH, and CRITICAL all force REVIEW even for safe actions
    with trusted provenance. Changing this band is a policy decision.
    """
    for action in ["NO_ACTION", "ENRICH"]:
        assert evaluate_deterministic_policy(
            _rec(action, severity="LOW"),
            authoritative_trusted_source=True,
        ) == "ALLOW"
        for severity in ["MEDIUM", "HIGH", "CRITICAL"]:
            assert evaluate_deterministic_policy(
                _rec(action, severity=severity),
                authoritative_trusted_source=True,
            ) == "REVIEW", f"{severity}+{action}+trusted must REVIEW"


def test_severity_band_is_low_only_even_without_trust():
    for action in ["NO_ACTION", "ENRICH"]:
        for severity in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            assert evaluate_deterministic_policy(
                _rec(action, severity=severity),
                authoritative_trusted_source=False,
            ) == "REVIEW"
