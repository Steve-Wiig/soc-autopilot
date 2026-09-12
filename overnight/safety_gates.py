"""
Pre-flight safety gates for LLM-generated code.
Catches regressions and hallucinations before expensive pytest runs.
"""
import re
import ast
import logging

logger = logging.getLogger(__name__)

def pre_flight_safety_check(proposed_code: str, original_file_path: str = "") -> tuple:
    """
    Fast-fail validation before committing to expensive pytest runs.
    Returns (is_safe: bool, message: str)
    """
    # 1. Prevent bare except regression
    if re.search(r'except\s+Exception\s*:\s*\n\s*pass', proposed_code):
        return False, "Bare 'except Exception:' with pass detected. Handle or log the exception."
    if re.search(r'\bexcept\s*:', proposed_code):
        return False, "REJECTED: Bare 'except' detected. Use 'except Exception as e:'."
    # 2. Prevent hardcoded absolute paths
    if re.search(r'''["'](/home/|/Users/|/tmp/)''', proposed_code):
        return False, "REJECTED: Hardcoded absolute path detected."
    # 3. AST Check: Ensure generator functions yielding resources have @contextmanager
    try:
        tree = ast.parse(proposed_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Check if it's a generator (has Yield or YieldFrom)
                has_yield = any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(node))
                has_contextmanager = any(
                    (isinstance(d, ast.Name) and d.id == 'contextmanager') or
                    (isinstance(d, ast.Attribute) and d.attr == 'contextmanager')
                    for d in node.decorator_list
                )
                if has_yield and not has_contextmanager and 'test' not in node.name.lower():
                    return False, f"REJECTED: Generator function '{node.name}' missing @contextmanager decorator."
    except SyntaxError as e:
        return False, f"REJECTED: Invalid Python syntax. {e}"

    logger.info(f"Pre-flight safety checks cleared for {original_file_path or 'proposed code'}.")
    return True, "PASSED: Pre-flight checks cleared."
