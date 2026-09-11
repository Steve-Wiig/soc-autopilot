import hashlib
import json
import string
from dataclasses import dataclass, asdict


def _normalize_advisory(text: str) -> str:
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split())


@dataclass(frozen=True)
class AdvisoryIdentity:
    """Deterministic identity for a specific advisory against source content."""
    file_path: str
    advisory_notes: str
    source_hash: str

    def __post_init__(self):
        fields = [self.file_path, self.advisory_notes, self.source_hash]
        if not all(isinstance(value, str) and value.strip() for value in fields):
            raise ValueError(
                "AdvisoryIdentity requires non-empty string fields."
            )

    def canonical_json(self) -> str:
        data = asdict(self)
        data["file_path"] = data["file_path"].strip()
        data["advisory_notes"] = _normalize_advisory(data["advisory_notes"])
        data["source_hash"] = data["source_hash"].strip()
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def fingerprint(self) -> str:
        """SHA-256 fingerprint of the canonical advisory identity."""
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()
