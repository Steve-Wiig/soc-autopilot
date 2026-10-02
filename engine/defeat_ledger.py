"""
engine/defeat_ledger.py
-----------------------
Pillar 1: The Memory Layer (Canonical Defeat Ledger).
Prevents the autonomous loop from burning API tokens on unfixable bugs.
"""
import ast
import hashlib
import logging
import os
import re
import time
from pathlib import Path

from engine.memory_store import load_records, append_record

ROOT = Path(__file__).resolve().parent.parent


LEDGER_PATH = ROOT / "overnight" / "defeat_ledger.jsonl"
DEFEAT_THRESHOLD = int(os.getenv("DEFEAT_THRESHOLD", "3"))  # 3 strikes and you're out


def _strip_docstrings(node: ast.AST) -> None:
    """Recursively strip docstrings from modules, classes, and functions in-place."""
    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        if (node.body and isinstance(node.body[0], ast.Expr) and
            isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)):
            node.body.pop(0)
    for child in ast.iter_child_nodes(node):
        _strip_docstrings(child)


def hash_ast(source_code: str) -> str:
    """
    Generates a deterministic hash of the code's structural logic.
    Ignores whitespace, comments, and docstrings.
    """
    try:
        tree = ast.parse(source_code)
        _strip_docstrings(tree)
        dump = ast.dump(tree, annotate_fields=True, include_attributes=False)
        return hashlib.sha256(
            dump.encode("utf-8")
        ).hexdigest()
    except SyntaxError:
        return hashlib.sha256(source_code.encode('utf-8')).hexdigest()


def normalize_traceback(traceback_text: str) -> str:
    """
    Strips absolute paths and line numbers from pytest tracebacks.
    """
    # Fix: Use a raw string and a robust regex to consume the full absolute path
    normalized = re.sub(r'/[^\s\'":]+', '<PATH>', traceback_text)
    normalized = re.sub(r'line \d+', 'line <N>', normalized)
    return re.sub(r'\s+', ' ', normalized).strip()


def check_and_record_defeat(
    file_path: str,
    source_code: str,
    traceback_text: str
) -> bool:
    """
    Append one defeat attempt event to the ledger.

    The ledger is append-only. State is derived from historical events.

    Args:
        file_path: Path of the file that was being fixed.
        source_code: The source code that was attempted.
        traceback_text: The traceback/error produced by the attempt.

    Returns:
        True if the number of recorded attempts for this signature
        has reached or exceeded DEFEAT_THRESHOLD, False otherwise.
    """

    ast_hash = hash_ast(source_code)

    tb_hash = hashlib.sha256(
        normalize_traceback(traceback_text).encode("utf-8")
    ).hexdigest()

    signature = f"{ast_hash}_{tb_hash}"

    attempts = 1

    for entry in load_records(LEDGER_PATH):
        if entry.get("signature") == signature:
            attempts += 1

    event = {
        "event": "DEFEAT_ATTEMPT",
        "signature": signature,
        "ast_hash": ast_hash,
        "tb_hash": tb_hash,
        "file_path": file_path,
        "attempt": attempts,
        "timestamp": time.time(),
    }

    append_record(
        LEDGER_PATH,
        event,
    )

    return attempts >= DEFEAT_THRESHOLD


def is_ast_defeated(source_code: str) -> bool:
    """
    Checks whether the given source code's AST has been recorded as
    defeated at least DEFEAT_THRESHOLD times in the ledger.

    Args:
        source_code: The source code to check against the defeat ledger.

    Returns:
        True when defeat history exceeds threshold, False otherwise.

    Raises:
        Exception: Re-raises any error encountered while reading the
            ledger, after logging it, so the caller fails closed.
    """

    ast_hash = hash_ast(source_code)

    attempts = 0

    try:
        for entry in load_records(LEDGER_PATH):
            if (
                entry.get("ast_hash") == ast_hash
                and entry.get("event") == "DEFEAT_ATTEMPT"
            ):
                attempts += 1

                if attempts >= DEFEAT_THRESHOLD:
                    return True

    except Exception as e:
        # HARDENED: Fail closed with telemetry
        logging.error(f'CONTROL-PLANE FAILURE in defeat_ledger.py: {e}')
        raise

    return False
