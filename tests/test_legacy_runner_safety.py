from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

LEGACY = (
    ROOT / "scripts" / "overnight_runner.py",
    ROOT / "scripts" / "build_feature.py",
    ROOT / "scripts" / "gated_harden_overnight_runner.sh",
)


def test_legacy_runners_are_disabled():
    for path in LEGACY:
        source = path.read_text()
        assert "DISABLED" in source


def test_legacy_runners_have_no_mutation_primitives():
    forbidden = (
        "git apply",
        "git add",
        "git commit",
        "git reset --hard",
        "git clean -fd",
        "subprocess.run([\"git\"",
        "propose_code.py",
        "--auto",
    )

    for path in LEGACY:
        source = path.read_text()
        for token in forbidden:
            assert token not in source


def test_legacy_runners_do_not_enable_unrestricted_development_cloud():
    for path in LEGACY:
        source = path.read_text()
        assert "SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY" not in source
        assert "SOC_AUTOPILOT_DEVELOPMENT_CLOUD" not in source
