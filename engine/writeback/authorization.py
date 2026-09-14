"""
Fail-closed authorization contract for live writeback.

Live external side effects require an explicit signed authorization
artifact bound to a deterministic decision and a specific target.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any


ENV_SECRET = "SOC_WRITEBACK_AUTH_SECRET"


class WritebackAuthorizationError(RuntimeError):
    """Raised when live writeback authorization is missing or invalid."""


@dataclass(frozen=True)
class WritebackAuthorization:
    decision_id: str
    target: str
    outcome: str
    expires_at: int
    signature: str

    def validate(self, *, expected_target: str, secret: str) -> None:
        if not self.decision_id.strip():
            raise WritebackAuthorizationError("Missing decision_id")

        if self.outcome != "ALLOW":
            raise WritebackAuthorizationError(
                f"Writeback requires ALLOW outcome, got {self.outcome!r}"
            )

        if self.target != expected_target:
            raise WritebackAuthorizationError(
                f"Authorization target mismatch: "
                f"expected {expected_target!r}, got {self.target!r}"
            )

        if self.expires_at <= int(time.time()):
            raise WritebackAuthorizationError(
                "Writeback authorization expired"
            )

        expected = _signature(
            self.decision_id,
            self.target,
            self.outcome,
            self.expires_at,
            secret,
        )

        if not hmac.compare_digest(self.signature, expected):
            raise WritebackAuthorizationError(
                "Invalid writeback authorization signature"
            )


def _signature(
    decision_id: str,
    target: str,
    outcome: str,
    expires_at: int,
    secret: str,
) -> str:
    canonical = "|".join(
        [decision_id, target, outcome, str(expires_at)]
    )

    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def issue_writeback_authorization(
    *,
    decision_id: str,
    target: str,
    outcome: str,
    expires_at: int,
    secret: str | None = None,
) -> str:
    secret = secret or os.environ.get(ENV_SECRET)

    if not secret:
        raise WritebackAuthorizationError(
            f"{ENV_SECRET} is required"
        )

    if outcome != "ALLOW":
        raise WritebackAuthorizationError(
            "Only ALLOW decisions can authorize writeback"
        )

    if expires_at <= int(time.time()):
        raise WritebackAuthorizationError(
            "Authorization expiry must be in the future"
        )

    payload = {
        "decision_id": decision_id,
        "target": target,
        "outcome": outcome,
        "expires_at": expires_at,
    }

    encoded = base64.urlsafe_b64encode(
        json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).decode("ascii").rstrip("=")

    return (
        encoded
        + "."
        + _signature(
            decision_id,
            target,
            outcome,
            expires_at,
            secret,
        )
    )


def parse_writeback_authorization(
    token: str,
    *,
    expected_target: str,
    secret: str | None = None,
) -> WritebackAuthorization:
    secret = secret or os.environ.get(ENV_SECRET)

    if not secret:
        raise WritebackAuthorizationError(
            f"{ENV_SECRET} is required"
        )

    if not isinstance(token, str) or "." not in token:
        raise WritebackAuthorizationError(
            "Malformed writeback authorization token"
        )

    encoded, signature = token.rsplit(".", 1)

    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode(
            padded.encode("ascii")
        )
        payload: dict[str, Any] = json.loads(
            raw.decode("utf-8")
        )
    except Exception as exc:
        raise WritebackAuthorizationError(
            "Malformed authorization payload"
        ) from exc

    try:
        auth = WritebackAuthorization(
            decision_id=str(payload["decision_id"]),
            target=str(payload["target"]),
            outcome=str(payload["outcome"]),
            expires_at=int(payload["expires_at"]),
            signature=str(signature),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WritebackAuthorizationError(
            "Incomplete authorization payload"
        ) from exc

    auth.validate(
        expected_target=expected_target,
        secret=secret,
    )

    return auth
