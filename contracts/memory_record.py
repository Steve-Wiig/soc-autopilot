"""
Memory record contracts.

Storage schema only.
No autonomous behavior.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class FailurePattern:
    fingerprint: str
    issue_category: str
    target: str
    failure_signature: str
    lesson: str
    attempt: int
    model: Optional[str] = None
    resolved: bool = False

    def to_dict(self):
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
