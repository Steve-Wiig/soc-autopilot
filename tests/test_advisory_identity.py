import pytest
from engine.advisory_identity import AdvisoryIdentity


def test_same_finding_same_fingerprint():
    id1 = AdvisoryIdentity(
        "engine/intake_wazuh.py",
        "Maintainability: complexity",
        "src_hash_1",
    )
    id2 = AdvisoryIdentity(
        "engine/intake_wazuh.py",
        "maintainability: complexity",
        "src_hash_1",
    )
    assert id1.fingerprint() == id2.fingerprint()


def test_different_file_different_fingerprint():
    id1 = AdvisoryIdentity(
        "engine/intake_wazuh.py",
        "maintainability: complexity",
        "src_hash_1",
    )
    id2 = AdvisoryIdentity(
        "engine/worker_vote.py",
        "maintainability: complexity",
        "src_hash_1",
    )
    assert id1.fingerprint() != id2.fingerprint()


def test_changed_source_hash_new_fingerprint():
    id1 = AdvisoryIdentity(
        "engine/intake_wazuh.py",
        "maintainability: complexity",
        "src_hash_1",
    )
    id2 = AdvisoryIdentity(
        "engine/intake_wazuh.py",
        "maintainability: complexity",
        "src_hash_2",
    )
    assert id1.fingerprint() != id2.fingerprint()


def test_changed_advisory_new_fingerprint():
    id1 = AdvisoryIdentity(
        "engine/intake_wazuh.py",
        "maintainability: complexity",
        "src_hash_1",
    )
    id2 = AdvisoryIdentity(
        "engine/intake_wazuh.py",
        "security: command injection",
        "src_hash_1",
    )
    assert id1.fingerprint() != id2.fingerprint()


def test_malformed_advisory_rejected_empty():
    with pytest.raises(ValueError):
        AdvisoryIdentity("", "maintainability", "src_hash_1")


def test_malformed_advisory_rejected_type():
    with pytest.raises(ValueError):
        AdvisoryIdentity(None, "maintainability", "src_hash_1")
