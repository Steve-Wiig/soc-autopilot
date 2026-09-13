"""
P0: prove the worker derives authoritative_trusted_source ONLY from
the canonical EventEnvelope and never from model output.

Static-source assertions. The worker is a while True loop; end-to-end
mocking is out of scope for this P0. These catch the exact regression
the handoff warned about (model trust leaking into authorization).
"""
import inspect
import re

from engine import slm_triage_worker as w


def _worker_source():
    return inspect.getsource(w)


def test_worker_uses_event_envelope_trust_labels():
    src = _worker_source()
    assert "event_envelope.trust_labels.provenance_verified" in src
    assert "event_envelope.trust_labels.sanitized" in src
    assert "not event_envelope.trust_labels.untrusted_content" in src


def test_worker_does_not_pass_model_trust_labels_to_policy():
    src = _worker_source()
    assert "raw_rec, 'trust_labels'" not in src
    assert "raw_rec.trust_labels" not in src


def test_worker_passes_authoritative_trusted_source_into_policy():
    src = _worker_source()
    assert "authoritative_trusted_source=authoritative_trusted_source" in src


def test_worker_does_not_shadow_canonical_envelope_with_recommendation():
    src = _worker_source()
    assert "event_envelope = EventEnvelope(**raw_dict)" in src
    assert "recommendation_envelope = RecommendationEnvelope(" in src
    assert re.search(r"^\s*envelope = RecommendationEnvelope\(", src, re.M) is None
