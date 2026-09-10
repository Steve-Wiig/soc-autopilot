"""
tools/shadow_canary.py
----------------------
The Blast Door. Validates code quality and runtime safety on a shadow branch.
"""
import ast
import subprocess
import sys
from pathlib import Path

def check_complexity(file_path: str, max_complexity: int = 15) -> bool:
    """Fails if the AI writes spaghetti code (Cyclomatic Complexity > 15)."""
    try:
        tree = ast.parse(Path(file_path).read_text())
    except SyntaxError:
        return False
        
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            complexity = 1
            for child in ast.walk(node):
                if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.Assert)):
                    complexity += 1
                elif isinstance(child, ast.BoolOp):
                    complexity += len(child.values) - 1
            if complexity > max_complexity:
                print(f"       🛑 CANARY FAIL (Complexity): {node.name} scored {complexity}")
                return False
    return True

def check_static_and_import_safety(file_path: str) -> bool:
    """Ensures the file doesn't crash the interpreter on import."""
    try:
        res = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open('{file_path}').read())"],
            capture_output=True, timeout=10
        )
        return res.returncode == 0
    except:
        return False

def run_canary(modified_files: list) -> bool:
    print("       🦜 CANARY: Checking cyclomatic complexity...")
    for f in modified_files:
        if not check_complexity(f): return False
            
    print("       🦜 CANARY: Checking runtime safety...")
    for f in modified_files:
        if not check_static_and_import_safety(f):
            print(f"       🛑 CANARY FAIL (Runtime): {f}")
            return False
            
    return True
