from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]


def _canary_block() -> str:
    source = (ROOT / "overnight" / "self_improver.py").read_text()
    start = source.index("if run_canary(modified_paths):")
    end = source.index("else:", start)
    return source[start:end]


def test_unmerged_canary_is_not_reported_as_merged():
    source = (ROOT / "overnight" / "self_improver.py").read_text()

    assert "CANARY PASSED: Merged to master" not in source
    assert "Canary passed; awaiting human review/merge" in source


def test_canary_records_shadow_pushed_not_applied():
    block = _canary_block()

    assert '"SHADOW_PUSHED"' in block
    assert '_record_ledger(' in block
    assert '"APPLIED"' not in block


def test_canary_does_not_store_proven_fix():
    block = _canary_block()

    assert "_store_proven_fix(" not in block


def test_pi_approval_is_not_code_application():
    source = (ROOT / "tools" / "pi_redis_ingestor.py").read_text()

    assert (
        '"PI_APPROVED" if verdict.get("approved") else "PI_REJECTED"'
        in source
    )
    assert (
        '"APPLIED" if verdict.get("approved") else "REJECTED"'
        not in source
    )


def test_live_ledger_is_valid_jsonl():
    ledger = ROOT / "overnight" / "improvement_ledger.jsonl"

    if not ledger.exists():
        return

    for line_no, line in enumerate(ledger.read_text().splitlines(), 1):
        if line.strip():
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"Invalid JSONL at line {line_no}: {exc}"
                ) from exc
