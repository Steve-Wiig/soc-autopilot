"""
engine/defeat_ledger.py
-----------------------
Pillar 1: The Memory Layer (Canonical Defeat Ledger).
Prevents the autonomous loop from burning API tokens on unfixable bugs.
"""
import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


LEDGER_PATH = ROOT / "overnight" / "defeat_ledger.jsonl"
DEFEAT_THRESHOLD = 3  # 3 strikes and you're out

def _strip_docstrings_and_comments(node: ast.AST):
    """Recursively strip docstrings from modules, classes, and functions."""
    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        if (node.body and isinstance(node.body[0], ast.Expr) and
            isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str)):
            node.body.pop(0)
    for child in ast.iter_child_nodes(node):
        _strip_docstrings_and_comments(child)

def hash_ast(source_code: str) -> str:
    """
    Generates a deterministic hash of the code's structural logic.
    Ignores whitespace, comments, and docstrings.
    """
    try:
        tree = ast.parse(source_code)
        _strip_docstrings_and_comments(tree)
        dump = ast.dump(tree, annotate_fields=True, include_attributes=False)
        return hashlib.sha256(dump.encode('utf-8')).hexdigest()[:16]
    except SyntaxError:
        return hashlib.sha256(source_code.encode('utf-8')).hexdigest()[:16]

def normalize_traceback(traceback_text: str) -> str:
    """
    Strips absolute paths and line numbers from pytest tracebacks.
    """
    # Fix: Use a raw string and a robust regex to consume the full absolute path
    normalized = re.sub(r'/[^\s\'":]+', '<PATH>', traceback_text)
    normalized = re.sub(r'line \d+', 'line <N>', normalized)
    return re.sub(r'\s+', ' ', normalized).strip()

def check_and_record_defeat(file_path: str, source_code: str, traceback_text: str) -> bool:
    """
    Checks if this exact failure has been seen before. 
    Records the attempt. Returns True if the item is now DEFEATED (quarantine it).
    """
    ast_hash = hash_ast(source_code)
    tb_hash = hashlib.sha256(normalize_traceback(traceback_text).encode('utf-8')).hexdigest()[:12]
    signature = f"{ast_hash}_{tb_hash}"
    
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    ledger = {}
    if LEDGER_PATH.exists():
        try:
            for line in LEDGER_PATH.read_text().splitlines():
                if line.strip():
                    entry = json.loads(line)
                    ledger[entry['signature']] = entry
        except Exception:
            pass
            
    if signature in ledger:
        ledger[signature]['attempts'] += 1
        ledger[signature]['last_file_path'] = file_path
    else:
        ledger[signature] = {
            'signature': signature,
            'ast_hash': ast_hash,
            'tb_hash': tb_hash,
            'attempts': 1,
            'last_file_path': file_path
        }
        
    with open(LEDGER_PATH, 'w') as f:
        for entry in ledger.values():
            f.write(json.dumps(entry) + '\n')
            
    is_defeated = ledger[signature]['attempts'] >= DEFEAT_THRESHOLD
    return is_defeated

def is_ast_defeated(source_code: str) -> bool:
    """
    Pre-flight check: Returns True if this file's AST is already quarantined.
    Prevents wasting API tokens on poisoned files.
    """
    ast_hash = hash_ast(source_code)
    if not LEDGER_PATH.exists():
        return False
    try:
        for line in LEDGER_PATH.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                if entry.get('ast_hash') == ast_hash and entry.get('attempts', 0) >= DEFEAT_THRESHOLD:
                    return True
    except Exception:
        pass
    return False
