from overnight.self_improver import _classify_issue_for_routing


def test_low_risk_performance_is_tdd_candidate():
    issue = {
        "category": "performance",
        "severity": "low",
        "effort": "trivial",
        "impact": "low",
        "description": "Precompile a regex instead of compiling it per call.",
    }

    assert _classify_issue_for_routing(issue) == "LOCAL_TDD"


def test_low_risk_maintainability_is_tdd_candidate():
    issue = {
        "category": "maintainability",
        "severity": "low",
        "effort": "small",
        "impact": "medium",
        "description": "Replace repeated literal with a module constant.",
    }

    assert _classify_issue_for_routing(issue) == "LOCAL_TDD"


def test_high_risk_security_boundary_requires_review():
    issue = {
        "category": "blueprint_compliance",
        "severity": "high",
        "effort": "small",
        "impact": "high",
        "description": (
            "Input is sent to an external LLM without secret redaction."
        ),
    }

    assert _classify_issue_for_routing(issue) == "REVIEW"


def test_high_risk_concurrency_requires_review():
    issue = {
        "category": "performance",
        "severity": "high",
        "effort": "small",
        "impact": "high",
        "description": (
            "Concurrent workers mutate shared state and create a race condition."
        ),
    }

    assert _classify_issue_for_routing(issue) == "REVIEW"


def test_blueprint_compliance_is_review_by_default():
    issue = {
        "category": "blueprint_compliance",
        "severity": "low",
        "effort": "trivial",
        "impact": "low",
        "description": "Minor conformance observation.",
    }

    assert _classify_issue_for_routing(issue) == "REVIEW"


def test_medium_uncertain_issue_is_review():
    issue = {
        "category": "performance",
        "severity": "medium",
        "effort": "small",
        "impact": "medium",
        "description": "Optimize an internal hot path.",
    }

    assert _classify_issue_for_routing(issue) == "REVIEW"


def test_high_risk_keywords_override_low_structural_metadata():
    issue = {
        "category": "maintainability",
        "severity": "low",
        "effort": "small",
        "impact": "low",
        "description": (
            "Refactor code involved in authentication and credential handling."
        ),
    }

    assert _classify_issue_for_routing(issue) == "REVIEW"

def test_low_risk_route_reaches_tdd_after_passing_baseline(tmp_path, monkeypatch):
    import overnight.self_improver as si

    target = tmp_path / "target.py"
    target.write_text("def example(x):\n    return x\n")

    calls = []

    monkeypatch.setattr(si, "ROOT", tmp_path)
    monkeypatch.setattr(si, "is_ast_defeated", lambda text: False)
    monkeypatch.setattr(si, "run_pytest_cached", lambda targets: None)

    def fake_tdd(description, target_file, api_keys):
        calls.append(("tdd", description, target_file))
        return "def test_generated():\n    assert False\n"

    monkeypatch.setattr(si, "_generate_tdd_test", fake_tdd)
    monkeypatch.setattr(
        si, "_escalate_to_manual",
        lambda *a, **k: calls.append(("manual",))
    )
    monkeypatch.setattr(si, "_record_ledger", lambda *a, **k: None)
    monkeypatch.setattr(si, "_forensic_analysis", lambda *a, **k: "")
    monkeypatch.setattr(si, "_retrieve_similar_fixes", lambda *a, **k: "")
    monkeypatch.setattr(si, "_retrieve_failed_patterns", lambda *a, **k: "")
    monkeypatch.setattr(si, "generate", lambda *a, **k: None)
    monkeypatch.setattr(si, "run_pytest", lambda *a, **k: "SIMULATED RED")

    result = si.apply_auto_fix(
        target,
        {
            "category": "performance",
            "severity": "low",
            "effort": "trivial",
            "impact": "low",
            "description": "Precompile a repeated regex.",
        },
        api_keys={},
    )

    assert any(call[0] == "tdd" for call in calls)
    assert not any(call[0] == "manual" for call in calls)
    assert result is False


def test_high_risk_route_skips_tdd_and_escalates(tmp_path, monkeypatch):
    import overnight.self_improver as si

    target = tmp_path / "target.py"
    target.write_text("def example(x):\n    return x\n")

    calls = []

    monkeypatch.setattr(si, "ROOT", tmp_path)
    monkeypatch.setattr(si, "is_ast_defeated", lambda text: False)
    monkeypatch.setattr(si, "run_pytest_cached", lambda targets: None)
    monkeypatch.setattr(
        si, "_generate_tdd_test",
        lambda *a, **k: calls.append(("tdd",))
    )
    monkeypatch.setattr(
        si, "_escalate_to_manual",
        lambda *a, **k: calls.append(("manual",))
    )
    monkeypatch.setattr(si, "_record_ledger", lambda *a, **k: None)

    result = si.apply_auto_fix(
        target,
        {
            "category": "blueprint_compliance",
            "severity": "high",
            "effort": "small",
            "impact": "high",
            "description": (
                "External LLM receives credentials without "
                "secret redaction."
            ),
        },
        api_keys={},
    )

    assert result is True
    assert ("manual",) in calls
    assert ("tdd",) not in calls


def test_low_risk_baseline_none_does_not_enter_failure_reporting(tmp_path, monkeypatch):
    import overnight.self_improver as si

    target = tmp_path / "target.py"
    target.write_text("def example(x):\n    return x\n")

    monkeypatch.setattr(si, "ROOT", tmp_path)
    monkeypatch.setattr(si, "is_ast_defeated", lambda text: False)
    monkeypatch.setattr(si, "run_pytest_cached", lambda targets: None)
    monkeypatch.setattr(
        si, "_generate_tdd_test",
        lambda *a, **k: "def test_generated():\n    assert False\n"
    )
    monkeypatch.setattr(si, "_record_ledger", lambda *a, **k: None)
    monkeypatch.setattr(si, "_escalate_to_manual", lambda *a, **k: None)
    monkeypatch.setattr(si, "_forensic_analysis", lambda *a, **k: "")
    monkeypatch.setattr(si, "_retrieve_similar_fixes", lambda *a, **k: "")
    monkeypatch.setattr(si, "_retrieve_failed_patterns", lambda *a, **k: "")
    monkeypatch.setattr(si, "generate", lambda *a, **k: None)
    monkeypatch.setattr(si, "run_pytest", lambda *a, **k: "SIMULATED RED")

    # The prior B3 bug raised TypeError on len(None) here.
    # Reaching this assertion proves the None baseline path is safe.
    result = si.apply_auto_fix(
        target,
        {
            "category": "maintainability",
            "severity": "low",
            "effort": "small",
            "impact": "low",
            "description": "Extract a repeated literal into a constant.",
        },
        api_keys={},
    )

    assert result is False


def test_routing_secret_substring_remains_conservative():
    import overnight.self_improver as si

    issue = {
        "category": "performance",
        "severity": "low",
        "effort": "small",
        "impact": "low",
        "description": (
            "Reduce allocations in a hot loop; "
            "secret sauce is unrelated wording."
        ),
    }

    assert si._classify_issue_for_routing(issue) == "REVIEW"

def test_high_risk_functional_category_overrides_stale_path(tmp_path, monkeypatch):
    import overnight.self_improver as si

    target = tmp_path / "target.py"
    target.write_text("def example(x):\n    return x\n")

    calls = []

    monkeypatch.setattr(si, "ROOT", tmp_path)
    monkeypatch.setattr(si, "is_ast_defeated", lambda text: False)
    monkeypatch.setattr(si, "run_pytest_cached", lambda targets: None)
    monkeypatch.setattr(
        si, "_escalate_to_manual",
        lambda *a, **k: calls.append(("manual",))
    )
    monkeypatch.setattr(si, "_record_ledger", lambda *a, **k: None)
    monkeypatch.setattr(
        si, "_generate_tdd_test",
        lambda *a, **k: calls.append(("tdd",))
    )

    result = si.apply_auto_fix(
        target,
        {
            "category": "bug",
            "severity": "high",
            "effort": "small",
            "impact": "high",
            "description": "Authentication bypass permits unauthorized access.",
        },
        api_keys={},
    )

    assert result is True
    assert ("manual",) in calls
    assert ("tdd",) not in calls


def test_generic_functional_finding_still_uses_stale_path(tmp_path, monkeypatch):
    import overnight.self_improver as si

    target = tmp_path / "target.py"
    target.write_text("def example(x):\n    return x\n")

    calls = []

    monkeypatch.setattr(si, "ROOT", tmp_path)
    monkeypatch.setattr(si, "is_ast_defeated", lambda text: False)
    monkeypatch.setattr(si, "run_pytest_cached", lambda targets: None)
    monkeypatch.setattr(
        si, "_escalate_to_manual",
        lambda *a, **k: calls.append(("manual",))
    )
    monkeypatch.setattr(si, "_record_ledger", lambda *a, **k: None)

    recorded = []

    monkeypatch.setattr(
        si, "_record_ledger",
        lambda *a, **k: recorded.append(a),
    )

    result = si.apply_auto_fix(
        target,
        {
            "category": "bug",
            "severity": "low",
            "effort": "small",
            "impact": "low",
            "description": "Fix an ordinary incorrect return value.",
        },
        api_keys={},
    )

    assert result is True
    assert not calls
    assert recorded
    assert recorded[-1][2] == "STALE"


def test_other_high_risk_functional_category_overrides_stale_path(
    tmp_path, monkeypatch
):
    import overnight.self_improver as si

    target = tmp_path / "target.py"
    target.write_text("def example(x):\n    return x\n")

    calls = []

    monkeypatch.setattr(si, "ROOT", tmp_path)
    monkeypatch.setattr(si, "is_ast_defeated", lambda text: False)
    monkeypatch.setattr(si, "run_pytest_cached", lambda targets: None)
    monkeypatch.setattr(
        si, "_escalate_to_manual",
        lambda *a, **k: calls.append(("manual",))
    )
    monkeypatch.setattr(si, "_record_ledger", lambda *a, **k: None)

    recorded = []
    monkeypatch.setattr(
        si, "_record_ledger",
        lambda *a, **k: recorded.append(a),
    )

    result = si.apply_auto_fix(
        target,
        {
            "category": "correctness",
            "severity": "high",
            "effort": "small",
            "impact": "high",
            "description": "SQL injection is possible through query construction.",
        },
        api_keys={},
    )

    assert result is True
    assert ("manual",) in calls
    assert recorded
    assert recorded[-1][2] == "ESCALATED"
