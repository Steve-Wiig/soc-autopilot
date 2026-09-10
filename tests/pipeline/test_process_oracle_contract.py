import importlib
import json
from pathlib import Path

import tools.process_oracle as process_oracle


def isolated_processor(tmp_path):
    module = importlib.reload(process_oracle)

    pending = tmp_path / "pending"
    approved = tmp_path / "approved"
    rejected = tmp_path / "rejected"
    nas = tmp_path / "nas"
    backlog = tmp_path / "backlog.json"

    for directory in (
        pending,
        approved,
        rejected,
        nas / "pending",
        nas / "approved",
        nas / "rejected",
    ):
        directory.mkdir(parents=True)

    module.LOCAL_PENDING = pending
    module.LOCAL_APPROVED = approved
    module.LOCAL_REJECTED = rejected
    module.NAS_PENDING = nas / "pending"
    module.NAS_APPROVED = nas / "approved"
    module.NAS_REJECTED = nas / "rejected"
    module.BACKLOG = backlog
    module.evacuate_if_needed = lambda: None
    module.load_api_keys = lambda: {"test": "key"}

    return module, pending, approved, rejected, backlog


def test_approved_proposal_persists_both_votes_and_reaches_backlog(
    monkeypatch, tmp_path
):
    module, pending, approved, rejected, backlog = isolated_processor(tmp_path)

    source = pending / "proposal.json"
    source.write_text(json.dumps({
        "proposal": "TEST APPROVAL",
        "target_file": "tests/example.py",
    }))

    monkeypatch.setattr(
        module,
        "get_consensus",
        lambda proposal, keys: (
            True,
            {"approve": True, "reason": "judge-1"},
            {"approve": True, "reason": "judge-2"},
        ),
    )

    module.main()

    assert not source.exists()

    result = approved / "proposal.json"
    assert result.exists()
    assert not (rejected / "proposal.json").exists()

    data = json.loads(result.read_text())

    assert data["votes"]["judge1"] == {
        "approve": True,
        "reason": "judge-1",
    }
    assert data["votes"]["judge2"] == {
        "approve": True,
        "reason": "judge-2",
    }

    entries = json.loads(backlog.read_text())
    assert len(entries) == 1
    assert entries[0]["file"] == "tests/example.py"
    assert entries[0]["issue"]["description"] == "TEST APPROVAL"


def test_rejected_proposal_persists_both_votes_and_skips_backlog(
    monkeypatch, tmp_path
):
    module, pending, approved, rejected, backlog = isolated_processor(tmp_path)

    source = pending / "proposal.json"
    source.write_text(json.dumps({
        "proposal": "TEST REJECTION",
        "target_file": "tests/example.py",
    }))

    monkeypatch.setattr(
        module,
        "get_consensus",
        lambda proposal, keys: (
            False,
            {"approve": True, "reason": "judge-1"},
            {"approve": False, "reason": "judge-2"},
        ),
    )

    module.main()

    assert not source.exists()

    result = rejected / "proposal.json"
    assert result.exists()
    assert not (approved / "proposal.json").exists()

    data = json.loads(result.read_text())

    assert data["votes"]["judge1"]["approve"] is True
    assert data["votes"]["judge2"]["approve"] is False

    assert not backlog.exists()


def test_processor_and_gate_share_three_value_contract():
    gate = Path("engine/consensus_gate.py").read_text()
    processor = Path("tools/process_oracle.py").read_text()

    assert "return approved, vote1, vote2" in gate
    assert "return approved, audit_log" not in gate
    assert "approved, v1, v2 = get_consensus" in processor
