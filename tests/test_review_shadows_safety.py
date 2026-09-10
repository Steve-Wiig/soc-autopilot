from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "tools" / "review_shadows.py").read_text()


def test_review_shadows_does_not_use_shell():
    assert "shell=True" not in SOURCE


def test_review_shadows_uses_argument_lists():
    assert '["git", "fetch", "origin"]' in SOURCE
    assert '["git", "checkout", base]' in SOURCE
    assert '["git", "merge", f"origin/{branch}"]' in SOURCE
    assert '["git", "push", "origin", base]' in SOURCE
    assert '["git", "push", "origin", "--delete", branch]' in SOURCE


def test_merge_path_fails_closed():
    start = SOURCE.index('elif choice == "A":')
    end = SOURCE.index('elif choice == "R":', start)
    merge_block = SOURCE[start:end]

    assert "try:" in merge_block
    assert "MERGE ABORTED" in merge_block
    assert "Shadow branch was preserved" in merge_block


def test_shadow_is_not_deleted_after_failed_merge_or_push():
    start = SOURCE.index('elif choice == "A":')
    end = SOURCE.index('elif choice == "R":', start)
    merge_block = SOURCE[start:end]

    failure_area = merge_block[
        merge_block.index("except RuntimeError"):
        merge_block.index("delete_result =")
    ]

    assert "return 1" in failure_area


def test_shadow_cleanup_failure_does_not_claim_cleanup_succeeded():
    start = SOURCE.index('elif choice == "A":')
    end = SOURCE.index('print("🎉 Merged into live codebase!")', start)
    merge_block = SOURCE[start:end]

    assert "Code was merged successfully; remote shadow " in merge_block
    assert "branch was NOT deleted." in merge_block


def test_reject_path_preserves_branch_on_delete_failure():
    start = SOURCE.index('elif choice == "R":')
    end = SOURCE.index('elif choice == "S":', start)
    reject_block = SOURCE[start:end]

    assert "REJECT FAILED" in reject_block
    assert "Remote shadow branch was preserved." in reject_block
    assert "return 1" in reject_block
