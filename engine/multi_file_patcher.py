"""
engine/multi_file_patcher.py
----------------------------
Applies atomic multi-file SEARCH/REPLACE blocks with LENIENT FUZZY MATCHING.
IMPROVEMENT #13: normalize indentation + variable window so slightly-off
SEARCH blocks still locate their target region.
"""
import re
import difflib
from pathlib import Path
from dataclasses import dataclass

@dataclass
class FilePatch:
    file_path: Path
    search: str
    replace: str

def parse_multi_file_diff(raw_diff: str, root_dir: Path) -> list[FilePatch]:
    patches = []
    pattern = re.compile(
        r'<<<<<<<\s+(.*?)\s*\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE',
        re.DOTALL
    )

    root = Path(root_dir).resolve()

    for match in pattern.finditer(raw_diff):
        rel_path = match.group(1).strip()
        candidate = Path(rel_path)

        if candidate.is_absolute():
            raise ValueError(
                f"Patch path must be repository-relative: {rel_path!r}"
            )

        resolved = (root / candidate).resolve(strict=False)

        try:
            resolved.relative_to(root)
        except ValueError:
            raise ValueError(
                f"Patch path escapes repository root: {rel_path!r}"
            ) from None

        search = match.group(2)
        replace = match.group(3)
        patches.append(FilePatch(resolved, search, replace))

    return patches

def _locate_region(original: str, search: str):
    """Return (start_line, window_size) or (-1, 0)."""
    orig_lines = original.splitlines(keepends=True)
    orig_stripped = [l.strip() for l in orig_lines]
    search_stripped = [l.strip() for l in search.splitlines()]
    n = len(search_stripped)
    if n == 0 or all(not s for s in search_stripped):
        return -1, 0

    # 1. Normalized exact match (same line count, ignore indent/trailing ws)
    for i in range(len(orig_stripped) - n + 1):
        if orig_stripped[i:i+n] == search_stripped:
            return i, n

    # 2. Fuzzy difflib over stripped lines, variable window (tolerates +/-1 line)
    target = "\n".join(search_stripped)
    best_score, best_start, best_size = 0.0, -1, n
    for size in (n-1, n, n+1):
        if size <= 0:
            continue
        for i in range(len(orig_stripped) - size + 1):
            chunk = "\n".join(orig_stripped[i:i+size])
            score = difflib.SequenceMatcher(None, chunk, target).ratio()
            if score > best_score:
                best_score, best_start, best_size = score, i, size
    if best_score > 0.80:
        return best_start, best_size
    return -1, 0

def apply_multi_file_patches(patches: list[FilePatch]) -> dict[Path, str]:
    modified_files = {}
    working_contents = {}

    for patch in patches:
        if not patch.file_path.exists():
            raise ValueError(f"File not found: {patch.file_path}")

        if patch.file_path not in working_contents:
            working_contents[patch.file_path] = patch.file_path.read_text()

        original = working_contents[patch.file_path]
        new_content = original

        if patch.search in original:
            new_content = original.replace(patch.search, patch.replace, 1)
        else:
            orig_lines = original.splitlines(keepends=True)
            start, size = _locate_region(original, patch.search)
            if start >= 0:
                replace_text = patch.replace
                if not replace_text.endswith("\n"):
                    replace_text += "\n"
                new_lines = (
                    orig_lines[:start]
                    + [replace_text]
                    + orig_lines[start + size:]
                )
                new_content = "".join(new_lines)
            else:
                raise ValueError(
                    f"Search block not found (exact & fuzzy) in {patch.file_path}"
                )

        working_contents[patch.file_path] = new_content
        modified_files[patch.file_path] = new_content

    return modified_files
