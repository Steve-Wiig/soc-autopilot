"""
P1-8: Tree-wide guard against NAS reintroduction.

The NAS was intentionally removed. Any re-introduction of NAS
references into production code must fail the test suite before it
can be shipped.

Diagnostic scripts (audit_*, analyze_*, p1_4_completion_*) contain the
NAS patterns as design intent, not runtime references, and are excluded.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCAN_DIRS = ["engine", "tools", "contracts", "overnight"]
SCAN_EXTS = {".py", ".sh"}

SKIP_NAMES = {
    "audit_nas_references_readonly.py",
    "audit_manual_review_readonly.py",
    "analyze_escalations_readonly.py",
    "analyze_escalations_readonly_v2.py",
    "analyze_escalations_readonly_v3.py",
    "p1_4_completion_gated_patch.py",
}

NAS_PATTERNS = re.compile(
    r"NAS_PENDING|NAS_APPROVED|NAS_REJECTED|NAS_BASE|NAS_DIR|NAS_DEST"
    r"|NAS_FILE|/mnt/backup-nas|to NAS|evacuate_if_needed"
)


def _iter_source_files():
    for d in SCAN_DIRS:
        root = REPO_ROOT / d
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in SCAN_EXTS:
                continue
            if p.name in SKIP_NAMES:
                continue
            if "__pycache__" in p.parts:
                continue
            yield p


def test_no_nas_references_in_production_code():
    hits = []
    for p in _iter_source_files():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if NAS_PATTERNS.search(line):
                hits.append(
                    f"{p.relative_to(REPO_ROOT)}:{i}: {line.strip()[:120]}"
                )
    assert not hits, (
        "NAS references reintroduced into production code:\n"
        + "\n".join(hits)
    )
