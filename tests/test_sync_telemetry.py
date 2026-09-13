import os
import sys
import tempfile
import pytest
import fcntl
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
import tools.sync_telemetry as syncer

@pytest.fixture
def sync_env(tmp_path):
    """Setup temporary directories and patch module constants."""
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    archive = tmp_path / "archive"
    archive.mkdir()
    lock = tmp_path / "sync.lock"

    # Create a dummy file in outbox
    (outbox / "pending_123.jsonl").write_text('{"test": 1}\n')

    # Patch the module constants
    syncer.LOCAL_OUTBOX = outbox
    syncer.ARCHIVE_DEST = archive
    syncer.LOCK_FILE = lock

    yield syncer, outbox, archive, lock

def test_empty_outbox(sync_env, capsys):
    syncer_mod, outbox, archive, lock = sync_env
    for f in outbox.iterdir(): f.unlink()

    syncer_mod.sync()
    assert "Outbox empty" in capsys.readouterr().out

def test_archive_inside_outbox_trap(sync_env, capsys):
    """verify_archive_destination must reject destinations inside the outbox."""
    syncer_mod, outbox, archive, lock = sync_env

    # Point the archive destination INSIDE the outbox
    syncer_mod.ARCHIVE_DEST = outbox / "archive"

    with patch('tools.sync_telemetry.subprocess.run') as mock_run:
        syncer_mod.sync()

    out = capsys.readouterr().out
    assert "inside outbox" in out
    mock_run.assert_not_called()

def test_normal_sync(sync_env, capsys):
    syncer_mod, outbox, archive, lock = sync_env

    with patch('tools.sync_telemetry.verify_archive_destination', return_value=True), \
         patch('tools.sync_telemetry.subprocess.run') as mock_run:

        mock_run.return_value = MagicMock(returncode=0)
        syncer_mod.sync()

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "rsync" in args
    assert "--remove-source-files" in args

def test_rsync_vanished_files(sync_env, capsys):
    syncer_mod, outbox, archive, lock = sync_env

    with patch('tools.sync_telemetry.verify_archive_destination', return_value=True), \
         patch('tools.sync_telemetry.subprocess.run') as mock_run:

        mock_run.return_value = MagicMock(returncode=24, stderr="vanished")
        syncer_mod.sync()

    assert "vanished source files" in capsys.readouterr().out

def test_concurrent_syncers(sync_env, capsys):
    syncer_mod, outbox, archive, lock = sync_env

    fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        # FIX: sync() now returns instead of sys.exit(0), so this won't raise SystemExit
        syncer_mod.sync()
        assert "Another syncer is already running" in capsys.readouterr().out
    finally:
        os.close(fd)
