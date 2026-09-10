from pathlib import Path

import pytest

from engine.multi_file_patcher import parse_multi_file_diff


def _diff(path: str) -> str:
    return (
        f"<<<<<<< {path}\n"
        "OLD\n"
        "=======\n"
        "NEW\n"
        ">>>>>>> REPLACE\n"
    )


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "../../outside.py",
        "engine/../../outside.py",
        "/tmp/outside.py",
    ],
)
def test_patch_target_must_remain_inside_repository(
    tmp_path: Path,
    path: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="repository-relative|escapes repository root",
    ):
        parse_multi_file_diff(_diff(path), tmp_path)


def test_valid_relative_patch_path_is_resolved(
    tmp_path: Path,
) -> None:
    parsed = parse_multi_file_diff(
        _diff("engine/../engine/safe.py"),
        tmp_path,
    )

    assert len(parsed) == 1
    assert parsed[0].file_path == (
        tmp_path / "engine" / "safe.py"
    ).resolve()


def test_symlink_target_outside_repository_is_rejected(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "p0_outside_target"
    outside.mkdir()

    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable")

    with pytest.raises(
        ValueError,
        match="escapes repository root",
    ):
        parse_multi_file_diff(
            _diff("linked/file.py"),
            tmp_path,
        )
