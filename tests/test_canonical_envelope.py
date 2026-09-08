from __future__ import annotations

import pytest
from pydantic import ValidationError
from datetime import datetime, timezone
import hashlib
import json

from engine.canonical_envelope import EventEnvelope, TrustLabels

def _make_payload():
    raw = {"alert": "test", "src_ip": "1.2.3.4"}
    raw_hash = hashlib.sha256(json.dumps(raw).encode()).hexdigest()
    return raw, raw_hash

def test_valid_envelope():
    raw, raw_hash = _make_payload()

    env = EventEnvelope(
        source="eve",
        collector_version="1.0.0",
        transform_version="1.0.0",
        original_payload_hash=raw_hash,
        normalized_payload_hash=raw_hash,
        payload=raw
    )

    assert env.source == "eve"
    assert env.trust_labels.untrusted_content is True
    assert env.schema_version == "1.0"

def test_rejects_invalid_source():
    raw, raw_hash = _make_payload()

    with pytest.raises(ValidationError):
        EventEnvelope(
            source="malicious_source", # Not in Literal["wazuh", "eve", "unknown"]
            collector_version="1.0.0",
            transform_version="1.0.0",
            original_payload_hash=raw_hash,
            normalized_payload_hash=raw_hash,
            payload=raw
        )

def test_rejects_extra_fields():
    raw, raw_hash = _make_payload()

    with pytest.raises(ValidationError):
        EventEnvelope(
            source="eve",
            collector_version="1.0.0",
            transform_version="1.0.0",
            original_payload_hash=raw_hash,
            normalized_payload_hash=raw_hash,
            payload=raw,
            execute_command="rm -rf /" # extra="forbid" will catch this
        )

def test_trust_labels_default_to_untrusted():
    labels = TrustLabels()
    assert labels.untrusted_content is True
    assert labels.sanitized is False
