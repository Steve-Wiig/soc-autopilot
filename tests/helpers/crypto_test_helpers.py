"""Test utilities for Ed25519-signed worker votes."""
import time
from contracts.worker_identity import WorkerVote
from contracts.worker_key_registry import WorkerKeyRegistry, sign_vote


def create_test_registry(worker_ids: list) -> WorkerKeyRegistry:
    """Create a registry with registered test workers."""
    registry = WorkerKeyRegistry()
    for wid in worker_ids:
        registry.register_worker(wid)
    return registry


def create_signed_vote(
    worker_id: str,
    candidate_hash: str,
    decision: str = "approve",
    registry: WorkerKeyRegistry = None,
) -> WorkerVote:
    """Create a properly Ed25519-signed WorkerVote for testing."""
    if registry is None:
        registry = WorkerKeyRegistry()
    if registry.get_private_key(worker_id) is None:
        registry.register_worker(worker_id)
    private_key = registry.get_private_key(worker_id)
    unsigned = WorkerVote(
        worker_id=worker_id,
        worker_class="test",
        worker_instance=f"test-{worker_id}",
        execution_host="localhost",
        software_version="1.0.0-test",
        candidate_hash=candidate_hash,
        decision=decision,
        timestamp=int(time.time()),
        signature="placeholder",
    )
    return sign_vote(unsigned, private_key)
