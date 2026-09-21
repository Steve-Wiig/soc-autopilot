"""Deterministic identity generation for advisories tied to source content."""

import hashlib
import json
import string
from dataclasses import dataclass, asdict
from typing import Dict


def _normalize_advisory(text: str) -> str:
    """Normalize advisory text for stable, case/punctuation-insensitive hashing.

    Lowercases the text, strips punctuation, and collapses whitespace so
    that semantically identical advisories produce the same fingerprint.
    """
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split())


@dataclass(frozen=True)
class AdvisoryIdentity:
    """Deterministic identity for a specific advisory against source content.

    Combines the file path, advisory notes, and a hash of the source content
    to produce a stable fingerprint that uniquely identifies an advisory
    for a given piece of source content.
    """
    file_path: str
    advisory_notes: str
    source_hash: str

    def __post_init__(self) -> None:
        """Validate that all identity fields are non-empty strings."""
        required_fields = [self.file_path, self.advisory_notes, self.source_hash]
        if not all(isinstance(value, str) and value.strip() for value in required_fields):
            raise ValueError(
                "AdvisoryIdentity requires non-empty string fields."
            )

    def canonical_json(self) -> str:
        """Serialize the identity to a canonical JSON string.

        Fields are trimmed and normalized (advisory notes are normalized
        for case/punctuation/whitespace) before serialization, and keys
        are sorted to ensure a deterministic representation.
        """
        data: Dict[str, str] = asdict(self)
        data["file_path"] = data["file_path"].strip()
        data["advisory_notes"] = _normalize_advisory(data["advisory_notes"])
        data["source_hash"] = data["source_hash"].strip()
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def fingerprint(self) -> str:
        """Compute the SHA-256 fingerprint of the canonical advisory identity."""
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()
