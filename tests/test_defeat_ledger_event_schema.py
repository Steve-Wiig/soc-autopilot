import json

from engine.defeat_ledger import (
    LEDGER_PATH,
    check_and_record_defeat,
)


def test_defeat_events_have_schema():
    code = "def broken(): return 1 / 0"

    check_and_record_defeat(
        "foo.py",
        code,
        "ZeroDivisionError",
    )

    record = json.loads(
        LEDGER_PATH.read_text().splitlines()[0]
    )

    assert record["event"] == "DEFEAT_ATTEMPT"
    assert "signature" in record
    assert "ast_hash" in record
    assert "tb_hash" in record
    assert "timestamp" in record
