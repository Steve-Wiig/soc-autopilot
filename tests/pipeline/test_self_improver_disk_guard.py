from pathlib import Path
from unittest.mock import patch

import overnight.self_improver as si


def test_disk_space_guard_rejects_low_free_space():
    with patch.object(
        si.shutil,
        "disk_usage",
        return_value=(30 * 1024**3, 29 * 1024**3, 1 * 1024**3),
    ):
        assert si._has_sufficient_disk_space() is False


def test_disk_space_guard_accepts_healthy_free_space():
    with patch.object(
        si.shutil,
        "disk_usage",
        return_value=(30 * 1024**3, 26 * 1024**3, 4 * 1024**3),
    ):
        assert si._has_sufficient_disk_space() is True
