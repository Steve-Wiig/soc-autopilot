"""
engine/multi_file_patcher.py
----------------------------
Applies atomic multi-file SEARCH/REPLACE blocks with LENIENT FUZZY MATCHING.
IMPROVEMENT #13: normalize indentation + variable window so slightly-off
SEARCH blocks still locate their target region.
"""
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Set, Union

from engine.protected_kernel import assert_not_protected


@dataclass
class FilePatch:
    """A single SEARCH/REPLACE patch targeting one file.

    Attributes:
        file_path: Resolved absolute path of the file to patch.
        search: The exact text block to search for in the file.
        replace: The text block to substitute in place of `search`.
    """
    file_path: Path
    search: str
    replace: str


def parse_multi_file_diff(raw_diff: str, root_dir: Path) -> list[FilePatch]:
    """Parse a raw multi-file diff blob into a list of `FilePatch` objects.

    Each patch block is expected in the form:

        <<<<<<< relative/path/to/file
        <search text>
        =======
        <replace text>
        >>>>>>> REPLACE

    Args:
        raw_diff: The raw diff text containing one or more patch blocks.
        root_dir: Repository root used to resolve and validate relative paths.

    Returns:
        A list of `FilePatch` instances with resolved absolute file paths.

    Raises:
        ValueError: If a patch path is absolute or escapes the repository root.
    """
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


def apply_multi_file_patches(
    patches: list[FilePatch],
    repo_root: Path,
    authorized_files: set[str | Path],
) -> dict[Path, str]:
    """Apply a list of `FilePatch` objects and return the resulting file contents.

    Each patch's target file must exist, resolve inside `repo_root`, and be
    present in `authorized_files`. Patches are applied against an in-memory
    working copy of each file's contents so multiple patches to the same
    file compose correctly.

    Args:
        patches: The patches to apply, in order.
        repo_root: Repository root directory used for path validation.
        authorized_files: Set of file paths (relative or absolute) that are
            authorized mutation targets.

    Returns:
        A mapping of absolute file path to its fully patched contents.

    Raises:
        ValueError: If a target file does not exist, is unauthorized, escapes
            the repository root, is protected, or the search text is not
            found exactly in the current file contents.
    """
    modified_files = {}
    working_contents = {}

    for patch in patches:
        if not patch.file_path.exists():
            raise ValueError(f"File not found: {patch.file_path}")

        # P0-2: path authorization is mandatory. No opt-out.
        try:
            rel_target = patch.file_path.relative_to(repo_root)
        except ValueError:
            raise ValueError(
                f"Patch path is outside repository root: {patch.file_path}"
            ) from None
        validate_mutation_target(repo_root, authorized_files, rel_target)

        if patch.file_path not in working_contents:
            working_contents[patch.file_path] = patch.file_path.read_text()

        original = working_contents[patch.file_path]
        new_content = original

        if patch.search in original:
            new_content = original.replace(patch.search, patch.replace, 1)
        else:
            raise ValueError(
                f"Exact patch match required: {patch.file_path}"
            )

        working_contents[patch.file_path] = new_content
        modified_files[patch.file_path] = new_content

    return modified_files


def validate_mutation_target(
    repo_root: Path,
    authorized_files: Set[Union[str, Path]],
    candidate_path: Union[str, Path],
) -> Path:
    """Validate that a mutation target is inside the repo and authorized.

    Performs the following checks, in order:
      1. Rejects absolute candidate paths.
      2. Ensures the resolved path stays within `repo_root` (no traversal).
      3. Ensures the resolved path is not part of the protected kernel.
      4. Ensures the resolved path is present in `authorized_files`.

    Args:
        repo_root: Repository root directory.
        authorized_files: Set of authorized file paths (relative or absolute).
        candidate_path: The path to validate, relative to `repo_root`.

    Returns:
        The resolved absolute `Path` of the validated target.

    Raises:
        ValueError: If the path is absolute, escapes the repository, or is
            not present in `authorized_files`.
    """
    repo_root = Path(repo_root).resolve()
    if isinstance(candidate_path, str):
        candidate_path = Path(candidate_path)

    # Reject absolute paths
    if candidate_path.is_absolute():
        raise ValueError(f"Absolute paths rejected: {candidate_path}")

    # Resolve and check containment
    resolved = (repo_root / candidate_path).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        raise ValueError(f"Path escapes repository: {candidate_path}")

    # PROTECTED KERNEL: refuse to mutate safety-critical files even
    # when the caller has authorized them. This gate sits below the
    # authorization boundary so a future caller cannot bypass it.
    assert_not_protected(resolved.relative_to(repo_root))

    # Check authorization
    auth_resolved = {(repo_root / Path(f)).resolve() for f in authorized_files}
    if resolved not in auth_resolved:
        raise ValueError(f"Path not authorized: {candidate_path}")

    return resolved


def _find_patch_location_strict(source: str, search_text: str) -> int:
    """Locate `search_text` within `source` using strict (non-fuzzy) matching.

    First attempts exact substring matching. If no exact match is found,
    falls back to a whitespace-normalized comparison, mapping the match
    position back to the original (non-normalized) source string.

    Args:
        source: The full text to search within.
        search_text: The text block to locate.

    Returns:
        The character index in `source` where `search_text` (or its
        whitespace-normalized equivalent) begins.

    Raises:
        ValueError: If multiple exact matches are found (ambiguous patch)
            or no match is found at all.
    """
    # Exact match
    exact_matches = []
    start = 0
    while True:
        time.sleep(0.1)  # Phase 4 Fix: Prevent CPU exhaustion in polling loop
        pos = source.find(search_text, start)
        if pos == -1:
            break
        exact_matches.append(pos)
        start = pos + 1

    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise ValueError(f"AMBIGUOUS PATCH: Found {len(exact_matches)} exact matches.")

    # Normalized exact match - handle multi-line properly
    normalized_search = ' '.join(search_text.split())
    normalized_source = ' '.join(source.split())

    norm_pos = normalized_source.find(normalized_search)
    if norm_pos != -1:
        # Map back to original position
        # Count characters before normalized position
        original_pos = 0
        norm_count = 0
        for i, char in enumerate(source):
            if not char.isspace():
                if norm_count == norm_pos:
                    original_pos = i
                    break
                norm_count += 1
            elif char in ' \t\n' and i > 0 and source[i - 1] in ' \t\n':
                continue
            else:
                norm_count += 1
        return original_pos

    raise ValueError("PATCH LOCATION NOT FOUND: Fuzzy matching disabled for autonomous mutation.")
