"""
engine/patch_parser.py
----------------------
Production-grade Search/Replace patch parser for soc-autopilot.

Enforces the Aider-style patch contract:

    <<<<<<< SEARCH
    ... lines to find in the original file ...
    =======
    ... lines to replace them with ...
    >>>>>>> REPLACE

This module is responsible for:
    1. Parsing raw LLM output into a list of ``PatchBlock`` instances.
    2. Locating each ``SEARCH`` block in the source file, using an exact
       match first and falling back to a fuzzy (similarity-ratio based)
       match when no exact match is found.
    3. Applying the resolved blocks to the source content while enforcing
       a scope budget and rejecting overlapping patches.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger("soc_autopilot.patch_parser")
logger.setLevel(logging.INFO)

MAX_LINES_CHANGED_PER_PATCH_SET = 500
FUZZY_SIMILARITY_THRESHOLD = 0.85
SEARCH_BLOCK_MARKER = "<<<<<<< SEARCH"
DIVIDER_MARKER = "======="
REPLACE_BLOCK_MARKER = ">>>>>>> REPLACE"


@dataclass(frozen=True)
class PatchBlock:
    """
    A single, resolved SEARCH/REPLACE unit.

    Attributes:
        search_lines: The exact lines the parser looked for in the source.
        replace_lines: The lines that should replace ``search_lines``.
        original_start_line: The zero-based line index in the source file
            where ``search_lines`` was located. ``-1`` until resolved by
            ``apply_patches``.
        is_fuzzy_match: ``True`` if the match was found via fuzzy matching
            rather than an exact match.
        similarity_ratio: The similarity ratio (0.0-1.0) used for fuzzy
            matching. ``1.0`` for exact matches.
    """

    search_lines: Tuple[str, ...]
    replace_lines: Tuple[str, ...]
    original_start_line: int = -1
    is_fuzzy_match: bool = False
    similarity_ratio: float = 1.0


@dataclass
class PatchResult:
    """
    The outcome of applying a set of ``PatchBlock`` instances to source content.

    Attributes:
        success: Whether the patch set was applied successfully.
        applied_blocks: Number of blocks that were applied.
        total_lines_changed: Sum of changed lines across all applied blocks.
        error_message: Optional error description if ``success`` is ``False``.
        modified_content: The resulting file content after patching.
        blocks: The resolved ``PatchBlock`` instances, in source order.
    """

    success: bool
    applied_blocks: int
    total_lines_changed: int
    error_message: Optional[str] = None
    modified_content: Optional[str] = None
    blocks: List[PatchBlock] = field(default_factory=list)


class PatchParseError(ValueError):
    """Raised when the raw LLM output cannot be parsed into patch blocks."""


class PatchApplyError(RuntimeError):
    """Raised when a parsed patch block cannot be applied to the source content."""


class ScopeBudgetExceededError(PatchApplyError):
    """Raised when the total number of changed lines exceeds the allowed budget."""


def parse_patch_blocks(raw_llm_output: str) -> List[PatchBlock]:
    """
    Parse raw LLM output into a list of unresolved ``PatchBlock`` instances.

    Args:
        raw_llm_output: The full text produced by the LLM, expected to
            contain one or more SEARCH/REPLACE blocks.

    Returns:
        A list of ``PatchBlock`` instances with ``search_lines`` and
        ``replace_lines`` populated. ``original_start_line`` is left at
        its default (``-1``) since it is only resolved during
        ``apply_patches``.

    Raises:
        PatchParseError: If no valid blocks are found, or if a block is
            malformed (missing divider/terminator, or empty on both sides).
    """
    blocks: List[PatchBlock] = []
    lines = raw_llm_output.splitlines(keepends=False)
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line != SEARCH_BLOCK_MARKER:
            idx += 1
            continue
        idx += 1
        search_start = idx
        while idx < len(lines) and lines[idx].strip() != DIVIDER_MARKER:
            idx += 1
        if idx >= len(lines):
            raise PatchParseError("Unterminated SEARCH block: Missing '=======' divider.")
        search_content = tuple(lines[search_start:idx])
        idx += 1
        replace_start = idx
        while idx < len(lines) and lines[idx].strip() != REPLACE_BLOCK_MARKER:
            idx += 1
        if idx >= len(lines):
            raise PatchParseError("Unterminated REPLACE block: Missing '>>>>>>> REPLACE' marker.")
        replace_content = tuple(lines[replace_start:idx])
        if not search_content and not replace_content:
            raise PatchParseError("Empty SEARCH and REPLACE block (No-op).")
        blocks.append(PatchBlock(search_lines=search_content, replace_lines=replace_content))
        idx += 1
    if not blocks:
        raise PatchParseError("No valid SEARCH/REPLACE blocks found in LLM output.")
    return blocks


def _calculate_lines_changed(search: Tuple[str, ...], replace: Tuple[str, ...]) -> int:
    """Return the number of lines changed by a block, used for scope budgeting."""
    return max(len(search), len(replace))


def _find_exact_match(source_lines: List[str], search_lines: Tuple[str, ...]) -> Optional[int]:
    """
    Find the first exact occurrence of ``search_lines`` within ``source_lines``.

    Args:
        source_lines: The lines of the source file.
        search_lines: The lines to search for, in order.

    Returns:
        The zero-based starting index of the match, or ``None`` if no
        exact match is found. An empty ``search_lines`` matches at index 0.
    """
    if not search_lines:
        return 0
    first_line = search_lines[0]
    search_len = len(search_lines)
    for idx, line in enumerate(source_lines):
        if line == first_line:
            if tuple(source_lines[idx: idx + search_len]) == search_lines:
                return idx
    return None


def _find_fuzzy_match(
    source_lines: List[str], search_lines: Tuple[str, ...]
) -> Optional[Tuple[int, float]]:
    """
    Find the best fuzzy match for ``search_lines`` within ``source_lines``.

    Slides a window of exactly ``len(search_lines)`` lines across the
    source and computes a similarity ratio against ``search_lines`` for
    each window, keeping the best result.

    Args:
        source_lines: The lines of the source file.
        search_lines: The lines to fuzzily match, in order.

    Returns:
        A tuple of ``(start_index, similarity_ratio)`` for the best match
        if its ratio meets ``FUZZY_SIMILARITY_THRESHOLD``, otherwise
        ``None``. An empty ``search_lines`` matches at index 0 with a
        ratio of ``1.0``.
    """
    if not search_lines:
        return (0, 1.0)
    search_str = "\n".join(search_lines)
    best_ratio = 0.0
    best_idx = -1
    search_len = len(search_lines)
    # Slide a window of the EXACT same size to prevent ratio dilution.
    for idx in range(len(source_lines) - search_len + 1):
        window = source_lines[idx: idx + search_len]
        matcher = difflib.SequenceMatcher(None, "\n".join(window), search_str, autojunk=False)
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_idx = idx
    if best_ratio >= FUZZY_SIMILARITY_THRESHOLD:
        return (best_idx, best_ratio)
    return None


def apply_patches(source_content: str, blocks: List[PatchBlock]) -> PatchResult:
    """
    Resolve and apply a list of ``PatchBlock`` instances to source content.

    Each block's ``search_lines`` is located in the source (exact match
    first, then fuzzy match), the total lines changed is checked against
    ``MAX_LINES_CHANGED_PER_PATCH_SET``, overlapping blocks are rejected,
    and the resolved blocks are applied from bottom to top so that earlier
    line indices remain valid.

    Args:
        source_content: The original file content.
        blocks: Unresolved ``PatchBlock`` instances, as produced by
            ``parse_patch_blocks``.

    Returns:
        A ``PatchResult`` describing the outcome, including the modified
        content and the resolved blocks (sorted by their original start
        line, descending).

    Raises:
        ScopeBudgetExceededError: If the cumulative lines changed exceeds
            ``MAX_LINES_CHANGED_PER_PATCH_SET``.
        PatchApplyError: If a SEARCH block cannot be located, or if two
            resolved blocks overlap.
    """
    source_lines = source_content.splitlines(keepends=False)
    total_lines_changed = 0
    resolved_blocks: List[PatchBlock] = []
    for block in blocks:
        lines_changed = _calculate_lines_changed(block.search_lines, block.replace_lines)
        total_lines_changed += lines_changed
        if total_lines_changed > MAX_LINES_CHANGED_PER_PATCH_SET:
            raise ScopeBudgetExceededError(
                f"Scope Budget Exceeded: {total_lines_changed} lines changed > "
                f"{MAX_LINES_CHANGED_PER_PATCH_SET} limit."
            )
        start_idx = _find_exact_match(source_lines, block.search_lines)
        is_fuzzy = False
        ratio = 1.0
        if start_idx is None:
            fuzzy_result = _find_fuzzy_match(source_lines, block.search_lines)
            if fuzzy_result:
                start_idx, ratio = fuzzy_result
                is_fuzzy = True
            else:
                raise PatchApplyError(
                    f"SEARCH block not found (Exact & Fuzzy < {FUZZY_SIMILARITY_THRESHOLD})."
                )
        resolved_blocks.append(
            PatchBlock(
                search_lines=block.search_lines,
                replace_lines=block.replace_lines,
                original_start_line=start_idx,
                is_fuzzy_match=is_fuzzy,
                similarity_ratio=ratio,
            )
        )
    resolved_blocks.sort(key=lambda b: b.original_start_line)
    for current_block, next_block in zip(resolved_blocks, resolved_blocks[1:]):
        current_end = current_block.original_start_line + len(current_block.search_lines)
        if current_end > next_block.original_start_line:
            raise PatchApplyError(
                f"Overlapping patches detected: Block at line "
                f"{current_block.original_start_line + 1} ends at {current_end}, "
                f"overlaps next block at {next_block.original_start_line + 1}."
            )
    working_lines = list(source_lines)
    resolved_blocks.sort(key=lambda b: b.original_start_line, reverse=True)
    for block in resolved_blocks:
        start = block.original_start_line
        end = start + len(block.search_lines)
        working_lines[start:end] = list(block.replace_lines)
    modified_content = "\n".join(working_lines)
    if source_content.endswith("\n") and not modified_content.endswith("\n"):
        modified_content += "\n"
    return PatchResult(
        success=True,
        applied_blocks=len(resolved_blocks),
        total_lines_changed=total_lines_changed,
        modified_content=modified_content,
        blocks=resolved_blocks,
    )


def process_llm_patch(source_content: str, llm_output: str) -> PatchResult:
    """
    Parse and apply a full LLM patch response to source content.

    Convenience wrapper combining ``parse_patch_blocks`` and
    ``apply_patches``, wrapping unexpected exceptions in a
    ``PatchApplyError`` for a consistent error surface.

    Args:
        source_content: The original file content.
        llm_output: The raw LLM output containing SEARCH/REPLACE blocks.

    Returns:
        A ``PatchResult`` describing the outcome.

    Raises:
        PatchParseError: If parsing fails.
        PatchApplyError: If applying the parsed blocks fails, including
            unexpected internal errors.
        ScopeBudgetExceededError: If the scope budget is exceeded.
    """
    try:
        blocks = parse_patch_blocks(llm_output)
        return apply_patches(source_content, blocks)
    except (PatchParseError, PatchApplyError, ScopeBudgetExceededError):
        raise
    except Exception as exc:
        raise PatchApplyError(f"Internal Engine Error: {exc}") from exc
