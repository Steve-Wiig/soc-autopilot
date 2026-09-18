#!/usr/bin/env python3
"""
Bounded development proposal CLI.

This command generates a bounded Aider proposal for human review.

It MUST NOT:
- auto-approve proposals;
- manufacture quorum votes;
- create Git commits;
- stage Git changes;
- reset or clean the canonical checkout;
- merge or promote changes.

The worker remains the implementation mechanism. Human review and promotion
remain authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts.promotion_state import PromotionState
from engine.development_candidate import DevelopmentCandidate
from engine.development_worker_dispatch import (
    DevelopmentWorkerRequest,
    dispatch_development_worker,
)


def _load_dotenv() -> None:
    """Load local development credentials without copying .env elsewhere."""
    env_path = ROOT / ".env"

    if not env_path.exists():
        return

    print(f"[ENV] Loading API keys from {env_path.name}...")

    for raw in env_path.read_text().splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a bounded development proposal for human review.",
    )

    parser.add_argument(
        "prompt",
        help="Task description for the implementation worker.",
    )

    parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        help="Explicit files the worker is allowed to modify.",
    )

    parser.add_argument(
        "--out-dir",
        default="proposals",
        help="Directory for generated proposal artifacts.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Worker timeout in seconds.",
    )

    return parser


def main() -> int:
    _load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  BOUNDED DEVELOPMENT PROPOSAL")
    print("=" * 60)
    print(f"  TASK:  {args.prompt}")
    print(f"  SCOPE: {', '.join(args.files)}")
    print("=" * 60)
    print()

    request = DevelopmentWorkerRequest(
        prompt=args.prompt,
        files=tuple(args.files),
        backend="aider",
        timeout=args.timeout,
    )

    print("[1/3] Dispatching bounded Aider worker...")

    dispatch_result = dispatch_development_worker(request)

    if not dispatch_result.accepted_for_review:
        print()
        print("[REJECTED] Worker did not produce an acceptable proposal.")
        print(f"Reason: {dispatch_result.reason}")
        return 1

    worker_result = dispatch_result.worker_result

    print()
    print(
        "[PASS] Worker produced a bounded proposal "
        f"({len(worker_result.diff)} diff bytes)."
    )

    changed = set(worker_result.changed_files)
    allowed = set(args.files)

    if not changed:
        print("[REJECTED] Worker produced no changed files.")
        return 1

    unauthorized = sorted(changed - allowed)

    if unauthorized:
        print("[REJECTED] Unauthorized changed paths:")
        for path in unauthorized:
            print(f"  {path}")
        return 1

    diff_sha256 = hashlib.sha256(
        worker_result.diff.encode("utf-8")
    ).hexdigest()

    candidate = DevelopmentCandidate.from_diff(
        candidate_id=f"prop-{diff_sha256[:16]}",
        base_commit="HEAD",
        diff_text=worker_result.diff,
        changed_files=list(worker_result.changed_files),
        generator_worker_id=(
            f"aider-{dispatch_result.backend}-"
            f"{worker_result.model_name}"
        ),
    )

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    patch_file = out_dir / f"{candidate.candidate_id}.patch"
    report_file = out_dir / f"{candidate.candidate_id}.md"

    patch_file.write_text(worker_result.diff)

    report_file.write_text(
        "\n".join(
            [
                f"# Development Proposal {candidate.candidate_id}",
                "",
                f"- State: `{PromotionState.PENDING_HUMAN_MERGE.value}`",
                "- Worker: Aider",
                f"- Worker model: `{worker_result.model_name}`",
                f"- Base commit: `{candidate.base_commit}`",
                f"- Diff SHA-256: `{candidate.diff_sha256}`",
                "",
                "## Changed files",
                "",
                *[f"- `{path}`" for path in candidate.changed_files],
                "",
                "## Worker reason",
                "",
                worker_result.reason,
                "",
                "## Human review",
                "",
                "This artifact is a proposal only.",
                "No quorum approval was manufactured.",
                "No Git commit was created by this command.",
                "Human review and promotion are required before merge.",
                "",
            ]
        )
    )

    print()
    print("[2/3] Proposal artifacts written:")
    print(f"  Patch:  {patch_file}")
    print(f"  Report: {report_file}")

    print()
    print("[3/3] STATUS")
    print(f"  {PromotionState.PENDING_HUMAN_MERGE.value}")
    print()
    print("No quorum was generated.")
    print("No Git staging was performed.")
    print("No Git commit was created.")
    print("Human review remains authoritative.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
