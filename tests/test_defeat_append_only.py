import pytest

from engine.defeat_ledger import (
    check_and_record_defeat,
    LEDGER_PATH,
)


@pytest.fixture(autouse=True)
def clean_ledger():
    if LEDGER_PATH.exists():
        LEDGER_PATH.unlink()

    yield

    if LEDGER_PATH.exists():
        LEDGER_PATH.unlink()


def test_defeat_ledger_is_append_only():
    code = "def broken(): return 1 / 0"
    tb = "ZeroDivisionError"

    check_and_record_defeat("foo.py", code, tb)
    check_and_record_defeat("foo.py", code, tb)
    check_and_record_defeat("foo.py", code, tb)

    lines = LEDGER_PATH.read_text().splitlines()

    # Three attempts should create three audit events
    assert len(lines) == 3
