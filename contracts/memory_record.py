"""
Memory record contracts.

Storage schema only.
No autonomous behavior.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class FailurePattern:
    """
    Represents a recorded failure pattern for a given issue/target.

    This is a pure data contract describing the shape of a failure
    record as persisted in storage. It does not implement any
    autonomous or business logic itself.
    """

    fingerprint: str
    issue_category: str
    target: str
    failure_signature: str
    lesson: str
    attempt: int
    model: Optional[str] = None
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert this failure pattern into a plain dictionary suitable
        for storage or serialization.

        Returns:
            A dictionary representation of the failure pattern,
            including a UTC timestamp of when this method was called.
        """
        return {
            "fingerprint": self.fingerprint,
            "issue_category": self.issue_category,
            "target": self.target,
            "failure_signature": self.failure_signature,
            "lesson": self.lesson,
            "attempt": self.attempt,
            "model": self.model,
            "resolved": self.resolved,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
