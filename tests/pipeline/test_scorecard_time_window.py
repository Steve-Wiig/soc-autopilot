from datetime import datetime, timedelta
import json


def _write_ledger(root, entries):
    path = (
        root
        / "overnight"
        / "improvement_ledger.jsonl"
    )
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "\n".join(
            json.dumps(entry)
            for entry in entries
        ) + "\n"
    )


def test_compute_scorecard_lifetime(
    tmp_path,
    monkeypatch,
):
    import overnight.self_improver as si

    now = datetime.now()

    _write_ledger(
        tmp_path,
        [
            {
                "timestamp": (
                    now - timedelta(days=30)
                ).isoformat(),
                "status": "APPLIED",
                "category": "maintainability",
            },
            {
                "timestamp": now.isoformat(),
                "status": "ESCALATED",
                "category": "performance",
            },
        ],
    )

    monkeypatch.setattr(si, "ROOT", tmp_path)

    scorecard = si.compute_scorecard()

    assert scorecard["total_decisions"] == 2
    assert scorecard["applied"] == 1
    assert scorecard["escalated"] == 1
    assert scorecard["malformed_timestamps"] == 0


def test_compute_scorecard_time_window(
    tmp_path,
    monkeypatch,
):
    import overnight.self_improver as si

    now = datetime.now()

    _write_ledger(
        tmp_path,
        [
            {
                "timestamp": (
                    now - timedelta(days=30)
                ).isoformat(),
                "status": "APPLIED",
                "category": "maintainability",
            },
            {
                "timestamp": now.isoformat(),
                "status": "ESCALATED",
                "category": "performance",
            },
        ],
    )

    monkeypatch.setattr(si, "ROOT", tmp_path)

    scorecard = si.compute_scorecard(days=7)

    assert scorecard["total_decisions"] == 1
    assert scorecard["applied"] == 0
    assert scorecard["escalated"] == 1


def test_compute_scorecard_malformed_timestamp(
    tmp_path,
    monkeypatch,
):
    import overnight.self_improver as si

    now = datetime.now()

    _write_ledger(
        tmp_path,
        [
            {
                "timestamp": "not-a-date",
                "status": "APPLIED",
                "category": "maintainability",
            },
            {
                "status": "ESCALATED",
                "category": "performance",
            },
            {
                "timestamp": now.isoformat(),
                "status": "REJECTED",
                "category": "security",
            },
        ],
    )

    monkeypatch.setattr(si, "ROOT", tmp_path)

    scorecard = si.compute_scorecard(days=7)

    assert scorecard["total_decisions"] == 1
    assert scorecard["rejected"] == 1
    assert scorecard["malformed_timestamps"] == 2


def test_compute_scorecard_rejects_negative_days():
    import overnight.self_improver as si

    try:
        si.compute_scorecard(days=-1)
    except ValueError as exc:
        assert "days" in str(exc).lower()
    else:
        raise AssertionError(
            "Expected ValueError"
        )


def test_compute_scorecard_rejects_boolean_days():
    import overnight.self_improver as si

    for value in (True, False):
        try:
            si.compute_scorecard(days=value)
        except ValueError as exc:
            assert "days" in str(exc).lower()
        else:
            raise AssertionError(
                "Expected ValueError"
            )


def test_compute_scorecard_handles_utc_z_timestamp(
    tmp_path,
    monkeypatch,
):
    import overnight.self_improver as si

    _write_ledger(
        tmp_path,
        [
            {
                "timestamp": "2099-01-01T00:00:00Z",
                "status": "APPLIED",
                "category": "maintainability",
            }
        ],
    )

    monkeypatch.setattr(si, "ROOT", tmp_path)

    scorecard = si.compute_scorecard(
        days=365000
    )

    assert scorecard["total_decisions"] == 1
    assert scorecard["applied"] == 1
    assert scorecard["malformed_timestamps"] == 0


def test_compute_scorecard_preserves_category_breakdown(
    tmp_path,
    monkeypatch,
):
    import overnight.self_improver as si

    now = datetime.now()

    _write_ledger(
        tmp_path,
        [
            {
                "timestamp": now.isoformat(),
                "status": "APPLIED",
                "category": "performance",
            },
            {
                "timestamp": (
                    now - timedelta(days=30)
                ).isoformat(),
                "status": "REJECTED",
                "category": "performance",
            },
        ],
    )

    monkeypatch.setattr(si, "ROOT", tmp_path)

    scorecard = si.compute_scorecard(days=7)

    assert scorecard["total_decisions"] == 1
    assert "performance" in scorecard[
        "category_breakdown"
    ]
    assert (
        scorecard["category_breakdown"]
        ["performance"]
        ["applied"]
        == 1
    )


def test_compute_scorecard_preserves_default_behavior(
    tmp_path,
    monkeypatch,
):
    import overnight.self_improver as si

    now = datetime.now()

    _write_ledger(
        tmp_path,
        [
            {
                "timestamp": (
                    now - timedelta(days=365)
                ).isoformat(),
                "status": "APPLIED",
                "category": "performance",
            },
            {
                "timestamp": now.isoformat(),
                "status": "REJECTED",
                "category": "performance",
            },
        ],
    )

    monkeypatch.setattr(si, "ROOT", tmp_path)

    assert (
        si.compute_scorecard()
        == si.compute_scorecard(days=None)
    )


def test_compute_scorecard_window_boundary(
    tmp_path,
    monkeypatch,
):
    import overnight.self_improver as si

    now = datetime.now()

    _write_ledger(
        tmp_path,
        [
            {
                "timestamp": (
                    now - timedelta(days=7)
                ).isoformat(),
                "status": "APPLIED",
                "category": "performance",
            }
        ],
    )

    monkeypatch.setattr(si, "ROOT", tmp_path)

    scorecard = si.compute_scorecard(days=7)

    assert scorecard["total_decisions"] in (0, 1)
    assert scorecard["malformed_timestamps"] == 0
