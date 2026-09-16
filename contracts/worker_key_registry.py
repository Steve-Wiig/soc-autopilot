"""Ed25519 key management for worker identity verification."""
import base64
import json
from pathlib import Path
from typing import Dict, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class WorkerKeyRegistry:
    """Registry mapping worker_id to Ed25519 public keys."""

    def __init__(self, store_path: Optional[str] = None):
        self._private_keys: Dict[str, Ed25519PrivateKey] = {}
        self._public_keys: Dict[str, Ed25519PublicKey] = {}
        self._store_path = Path(store_path) if store_path else None
        if self._store_path and self._store_path.exists():
            self._load()

    def register_worker(self, worker_id: str) -> Ed25519PrivateKey:
        private_key = Ed25519PrivateKey.generate()
        self._private_keys[worker_id] = private_key
        self._public_keys[worker_id] = private_key.public_key()
        if self._store_path:
            self._save()
        return private_key

    def get_public_key(self, worker_id: str) -> Optional[Ed25519PublicKey]:
        return self._public_keys.get(worker_id)

    def get_private_key(self, worker_id: str) -> Optional[Ed25519PrivateKey]:
        return self._private_keys.get(worker_id)

    def _save(self) -> None:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        data = {}
        for wid, pk in self._public_keys.items():
            data[wid] = base64.b64encode(
                pk.public_bytes(Encoding.Raw, PublicFormat.Raw)
            ).decode("ascii")
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        data = json.loads(self._store_path.read_text())
        for wid, pk_b64 in data.items():
            key_bytes = base64.b64decode(pk_b64)
            self._public_keys[wid] = Ed25519PublicKey.from_public_bytes(key_bytes)


def sign_vote(vote, private_key: Ed25519PrivateKey):
    """Sign a WorkerVote and return a new instance with the Ed25519 signature."""
    from contracts.worker_identity import WorkerVote
    payload = vote.signing_payload().encode("utf-8")
    sig = private_key.sign(payload)
    sig_b64 = base64.b64encode(sig).decode("ascii")
    return WorkerVote(
        worker_id=vote.worker_id,
        worker_class=vote.worker_class,
        worker_instance=vote.worker_instance,
        execution_host=vote.execution_host,
        software_version=vote.software_version,
        candidate_hash=vote.candidate_hash,
        decision=vote.decision,
        timestamp=vote.timestamp,
        task_id=vote.task_id,
        signature=sig_b64,
    )
