from __future__ import annotations

import pytest
from pydantic import ValidationError
from engine.dry_run_executor import simulate_action, ActionRequest

def test_block_ip_simulation_is_safe():
    req = ActionRequest(action_type="block_ip", target_id="203.0.113.5", reason="C2 Server")
    res = simulate_action(req)

    assert res.would_execute is True
    assert res.live_mutation is False  # CRITICAL: Must never be true in this phase
    assert res.is_reversible is True
    assert "firewall rule" in res.rollback_plan.lower()

def test_isolate_host_shows_blast_radius():
    req = ActionRequest(action_type="isolate_host", target_id="WORKSTATION-44", reason="Ransomware")
    res = simulate_action(req)

    assert res.live_mutation is False
    assert res.affected_assets == 1
    assert res.affected_critical_services >= 1
    assert res.estimated_downtime_minutes > 0

def test_rejects_unknown_action():
    # Pydantic catches the invalid Literal at object creation time!
    with pytest.raises(ValidationError):
        ActionRequest(action_type="launch_missiles", target_id="silo_1", reason="test")
