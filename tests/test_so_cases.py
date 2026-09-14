import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import json
from unittest.mock import patch, mock_open, MagicMock
from engine.writeback.so_cases import sanitize_input, write_to_ledger, create_case, main
import time
from engine.writeback.authorization import issue_writeback_authorization


def _live_authorization():
    return issue_writeback_authorization(
        decision_id="DEC-TEST-SO",
        target="so_cases",
        outcome="ALLOW",
        expires_at=int(time.time()) + 300,
        secret="unit-test-writeback-secret",
    )


def test_sanitize_input():
    data = {"a" * 100: "b" * 3000, "valid": "data"}
    result = sanitize_input(data)
    assert len(list(result.keys())[0]) == 64
    assert len(list(result.values())[0]) == 2048
    assert result["valid"] == "data"
    assert sanitize_input("not a dict") == {}

def test_write_to_ledger_success():
    with patch("builtins.open", mock_open()) as mocked_file:
        write_to_ledger("ref123", "case456")
        mocked_file.assert_called_once_with("handoffs_ledger.log", "a")
        handle = mocked_file()
        handle.write.assert_called()

def test_write_to_ledger_failure():
    with patch("builtins.open", side_effect=IOError):
        with pytest.raises(RuntimeError, match="Library code called exit\\(2\\)"):
            write_to_ledger("ref", "id")

@patch("engine.writeback.so_cases._HTTP_SESSION.post")
def test_create_case_api_success(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "SO-123"}
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response
    
    result = create_case("http://test", "key", {"test": "data"}, False, authorization=_live_authorization())
    assert result == "SO-123"
    mock_post.assert_called_once()

@patch("engine.writeback.so_cases._HTTP_SESSION.post")
def test_create_case_api_failure(mock_post):
    mock_post.side_effect = Exception("Connection Error")
    with pytest.raises(RuntimeError, match="Library code called exit\\(1\\)"):
        create_case("http://test", "key", {"test": "data"}, False, authorization=_live_authorization())

def test_create_case_draft_mode():
    result = create_case("http://test", "key", {"test": "data"}, True)
    assert result == "DRAFT_ID_000"

@patch("argparse.ArgumentParser.parse_args")
def test_main_invalid_json(mock_args):
    mock_args.return_value = MagicMock(
        url="http://test", 
        key="key", 
        payload="invalid-json", 
        draft=False
    )
    # The source code snippet provided ends abruptly at 'ra', 
    # assuming it raises an error or exits.
    with pytest.raises(Exception):
        main()