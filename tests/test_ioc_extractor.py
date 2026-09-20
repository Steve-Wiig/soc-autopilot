"""Tests for engine/ioc_extractor.py — extract_iocs function.
Based on actual implementation: uses psycopg2.connect("dbname=soc_memory user=orchestrator")
and execute_values() for bulk insert.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.ioc_extractor import extract_iocs


def _make_mock_psycopg2():
    """Create a properly structured psycopg2 mock."""
    mock_pg = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_pg.connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.connection.encoding = "UTF8"
    mock_cursor.fetchall.return_value = []
    mock_cursor.rowcount = 0
    # Mock Error class so except psycopg2.Error works
    mock_pg.Error = Exception
    return mock_pg


def test_extract_iocs_returns_int():
    """extract_iocs should return an integer count of IOCs extracted."""
    alert = {
        "alert_id": "test-001",
        "description": "Suspicious connection to 192.168.1.100",
        "severity": "high",
        "fields": ["network"],
    }

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = MagicMock()
    with patch("engine.ioc_extractor.get_pg_conn", return_value=mock_conn):
        with patch("engine.ioc_extractor.execute_values") as mock_ev:
            result = extract_iocs(alert)

    assert isinstance(result, int)
    assert result >= 0


def test_extract_iocs_empty_alert():
    """An alert with no extractable content should return 0."""
    alert = {
        "alert_id": "test-002",
        "description": "Nothing interesting here",
        "severity": "low",
        "fields": [],
    }

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = MagicMock()
    with patch("engine.ioc_extractor.get_pg_conn", return_value=mock_conn):
        with patch("engine.ioc_extractor.execute_values") as mock_ev:
            result = extract_iocs(alert)

    assert result == 0


def test_extract_iocs_handles_minimal_structure():
    """Should not crash on minimal/malformed alert structure."""
    alert = {"alert_id": "test-003"}

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = MagicMock()
    with patch("engine.ioc_extractor.get_pg_conn", return_value=mock_conn):
        with patch("engine.ioc_extractor.execute_values") as mock_ev:
            result = extract_iocs(alert)

    assert isinstance(result, int)
