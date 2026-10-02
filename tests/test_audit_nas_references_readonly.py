from typing import List, Tuple

def test_audit_nas_references_readonly() -> None:
    """
    Tests the audit_nas_references_readonly function.
    """
    # Mock the main function to capture output
    from unittest.mock import patch
    from io import StringIO

    with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
        from tools.diagnostics.audit_nas_references_readonly import main
        main()

    output = mock_stdout.getvalue()
    assert "soc-autopilot :: read-only NAS reference audit" in output
    assert "repo root:" in output
    assert "files scanned:" in output
    assert "files with hits:" in output
    assert "All reads completed. No writes were performed." in output
