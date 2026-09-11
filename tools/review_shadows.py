#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def run(cmd):
    """Run a command without a shell and return stdout plus exit code."""
    result = subprocess.run(
        cmd,
        shell=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def require_success(label, result):
    """Raise on command failure so governance operations fail closed."""
    stdout, returncode, stderr = result
    if returncode != 0:
        detail = stderr or stdout or "no diagnostic output"
        raise RuntimeError(
            f"{label} failed with exit code {returncode}: {detail[:500]}"
        )
    return stdout


def main():
    print("\n🔍 Fetching pending AI patches from GitHub...")
    require_success(
        "git fetch origin",
        run(["git", "fetch", "origin"]),
    )

    remote_refs, rc, stderr = run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/remotes/origin/shadow/autofix",
        ]
    )

    if rc != 0:
        print(f"❌ Failed to discover shadow branches: {stderr[:500]}")
        return 1

    branches = [
        ref.removeprefix("origin/")
        for ref in remote_refs.splitlines()
        if ref.strip()
    ]

    if not branches:
        print(
            "✅ No pending shadow branches. "
            "The AI hasn't generated any new patches today."
        )
        return 0

    print(f"📦 Found {len(branches)} pending patches for your review.\n")

    base_out, base_rc, base_stderr = run(
        ["git", "branch", "--show-current"]
    )

    if base_rc != 0:
        print(f"❌ Could not determine current branch: {base_stderr[:500]}")
        return 1

    base = base_out.strip()

    if not base:
        print("❌ Detached HEAD state. Aborting.")
        return 1

    for i, branch in enumerate(branches, 1):
        print("=" * 70)
        print(f"  🔎 REVIEW [{i}/{len(branches)}]: {branch}")
        print("=" * 70)

        msg, msg_rc, msg_err = run(
            ["git", "log", f"origin/{branch}", "-1", "--pretty=%B"]
        )
        if msg_rc != 0:
            print(f"❌ Unable to inspect {branch}: {msg_err[:500]}")
            continue

        print("📝 WHAT IS IT TRYING TO FIX?")
        print(f"   {msg}\n")

        files, files_rc, files_err = run(
            [
                "git",
                "diff",
                "--name-only",
                f"origin/{base}...origin/{branch}",
            ]
        )
        if files_rc != 0:
            print(f"❌ Unable to inspect changed files: {files_err[:500]}")
            continue

        print("📂 FILES CHANGED (Blast Radius):")
        if files:
            for f in files.splitlines():
                print(f"   - {f}")
        else:
            print("   (none)")
        print()

        stats, stats_rc, stats_err = run(
            [
                "git",
                "diff",
                f"origin/{base}...origin/{branch}",
                "--stat",
            ]
        )
        if stats_rc != 0:
            print(f"❌ Unable to inspect churn: {stats_err[:500]}")
            continue

        print("📊 CHURN (Lines added/removed):")
        print(f"   {stats}\n")

        print("ACTIONS:")
        print("  [W] Web Review (Open GitHub to see highlighted code diff)")
        print("  [A] Approve & Merge (Apply to your live codebase)")
        print("  [R] Reject & Delete (Throw it away)")
        print("  [S] Skip (Leave for later)")
        print("  [Q] Quit")

        while True:
            choice = input("\nChoose action [W/A/R/S/Q]: ").strip().upper()

            if choice == "W":
                url = (
                    "https://github.com/Steve-Wiig/soc-autopilot/"
                    f"compare/{base}...{branch}"
                )
                print(f"🌐 Opening: {url}")

                for cmd in ("xdg-open", "open", "start"):
                    try:
                        if subprocess.run(
                            [cmd, url],
                            capture_output=True,
                            check=False,
                        ).returncode == 0:
                            break
                    except OSError:
                        continue

                input("Press Enter when done reviewing in browser...")

            elif choice == "A":
                print("✅ Approving and merging...")

                try:
                    require_success(
                        f"checkout {base}",
                        run(["git", "checkout", base]),
                    )

                    require_success(
                        f"merge {branch}",
                        run(["git", "merge", f"origin/{branch}"]),
                    )

                    require_success(
                        f"push {base}",
                        run(["git", "push", "origin", base]),
                    )

                except RuntimeError as exc:
                    print(f"❌ MERGE ABORTED: {exc}")
                    print(
                        "🛑 Shadow branch was preserved for recovery/review."
                    )
                    return 1

                delete_result = run(
                    ["git", "push", "origin", "--delete", branch]
                )

                if delete_result[1] != 0:
                    print(
                        "⚠️ Base branch push succeeded, but shadow cleanup "
                        f"failed: {delete_result[2] or delete_result[0]}"
                    )
                    print(
                        "✅ Code was merged successfully; remote shadow "
                        "branch was NOT deleted."
                    )
                    break

                print("🎉 Merged into live codebase!")
                break

            elif choice == "R":
                print("🗑️ Rejecting and deleting branch...")

                try:
                    require_success(
                        f"delete remote shadow branch {branch}",
                        run(["git", "push", "origin", "--delete", branch]),
                    )
                except RuntimeError as exc:
                    print(f"❌ REJECT FAILED: {exc}")
                    print(
                        "🛑 Remote shadow branch was preserved."
                    )
                    return 1

                print("Deleted.")
                break

            elif choice == "S":
                print("Skipped.")
                break

            elif choice == "Q":
                sys.exit(0)

            else:
                print("Invalid choice.")

    print("\n✅ All done. You're caught up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
