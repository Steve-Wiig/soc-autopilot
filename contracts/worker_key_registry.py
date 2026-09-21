"""Ed25519 key management for worker identity verification.

This module provides a small in-memory (optionally disk-backed) registry
that maps a ``worker_id`` to an Ed25519 key pair, along with a helper to
sign a ``WorkerVote`` using a worker's private key.
"""
import base64
import json
from pathlib import Path
from typing import Dict, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class WorkerKeyRegistry:
    """Registry mapping worker_id to Ed25519 key pairs.

    Private keys are only ever held in memory. Public keys may optionally
    be persisted to disk (as base64-encoded raw bytes in a JSON file) so
    they can be reloaded across process restarts for signature
    verification.
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        """Initialize the registry.

        Args:
            store_path: Optional path to a JSON file used to persist and
                reload public keys. If the file already exists, its
                contents are loaded immediately.
        """
        self._private_keys: Dict[str, Ed25519PrivateKey] = {}
        self._public_keys: Dict[str, Ed25519PublicKey] = {}
        self._store_path: Optional[Path] = Path(store_path) if store_path else None
        if self._store_path and self._store_path.exists():
            self._load_from_disk()

    def register_worker(self, worker_id: str) -> Ed25519PrivateKey:
        """Generate and register a new Ed25519 key pair for a worker.

        Args:
            worker_id: Unique identifier of the worker to register.

        Returns:
            The newly generated Ed25519 private key for the worker.
        """
        private_key = Ed25519PrivateKey.generate()
        self._private_keys[worker_id] = private_key
        self._public_keys[worker_id] = private_key.public_key()
        if self._store_path:
            self._save_to_disk()
        return private_key

    def get_public_key(self, worker_id: str) -> Optional[Ed25519PublicKey]:
        """Look up the public key registered for a worker.

        Args:
            worker_id: Unique identifier of the worker.

        Returns:
            The worker's Ed25519 public key, or ``None`` if not registered.
        """
        return self._public_keys.get(worker_id)

    def get_private_key(self, worker_id: str) -> Optional[Ed25519PrivateKey]:
        """Look up the private key registered for a worker.

        Args:
            worker_id: Unique identifier of the worker.

        Returns:
            The worker's Ed25519 private key, or ``None`` if not registered.
        """
        return self._private_keys.get(worker_id)

    def _save_to_disk(self) -> None:
        """Persist all known public keys to ``self._store_path`` as JSON.

        Keys are stored as base64-encoded raw Ed25519 public key bytes.
        """
        # Imported here (rather than at module level) to avoid a potential
        # circular import with the serialization module at import time.
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        data: Dict[str, str] = {}
        for worker_id, public_key in self._public_keys.items():
            data[worker_id] = base64.b64encode(
                public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
            ).decode("ascii")
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(json.dumps(data, indent=2))

    def _load_from_disk(self) -> None:
        """Load public keys from ``self._store_path`` into memory."""
        data = json.loads(self._store_path.read_text())
        for worker_id, public_key_b64 in data.items():
            key_bytes = base64.b64decode(public_key_b64)
            self._public_keys[worker_id] = Ed25519PublicKey.from_public_bytes(key_bytes)


def sign_vote(vote, private_key: Ed25519PrivateKey):
    """Sign a ``WorkerVote`` and return a new signed instance.

    Args:
        vote: The unsigned ``WorkerVote`` to sign.
        private_key: The Ed25519 private key used to produce the signature.

    Returns:
        A new ``WorkerVote`` identical to ``vote`` but with its
        ``signature`` field populated with the base64-encoded Ed25519
        signature over the vote's signing payload.
    """
    # Imported here (rather than at module level) to avoid a circular
    # import with contracts.worker_identity, which may import from this
    # module.
    from contracts.worker_identity import WorkerVote

    payload = vote.signing_payload().encode("utf-8")
    signature = private_key.sign(payload)
    signature_b64 = base64.b64encode(signature).decode("ascii")
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
        signature=signature_b64,
    )
