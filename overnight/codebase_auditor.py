#!/usr/bin/env python3
"""
Comprehensive Codebase Auditor & Auto-Fixer.
Scans the project for systemic LLM generation errors and fixes/reports them.
"""
import ast
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = ["engine", "orchestrator", "memory", "tools"]

class Auditor:
    def __init__(self):
        self.fixes_applied = 0
        self.alignment_issues = []

    # --- PASS 1: AUTO-FIX KNOWN SYSTEMIC BUGS ---
    def pass1_auto_fix(self):
        print("\n" + "="*60)
        print("PASS 1: AUTO-FIXING SYSTEMIC BUGS (Datetime, sys.exit)")
        print("="*60)
        
        for d in TARGET_DIRS:
            for py_file in (ROOT / d).rglob("*.py"):
                if "__pycache__" in str(py_file): continue
                
                content = py_file.read_text()
                original = content

                # Fix 1A: datetime.utcnow() deprecation (Python 3.12+)
                if "datetime.utcnow()" in content or "datetime.datetime.utcnow()" in content:
                    # Ensure timezone is imported
                    if "from datetime import datetime" in content and "timezone" not in content.split("from datetime import datetime")[1].split("\n")[0]:
                        content = content.replace("from datetime import datetime", "from datetime import datetime, timezone")
                    elif "import datetime" in content and "timezone" not in content:
                        content = content.replace("import datetime", "import datetime\nfrom datetime import timezone")
                    
                    content = content.replace("datetime.utcnow()", "datetime.now(timezone.utc)")
                    content = content.replace("datetime.datetime.utcnow()", "datetime.now(timezone.utc)")

                # Fix 1B: sys.exit() in library code (outside __main__)
                # We use a simple heuristic: if sys.exit is not indented under if __name__
                lines = content.split('\n')
                in_main = False
                for i, line in enumerate(lines):
                    if 'if __name__ == "__main__":' in line or "if __name__ == '__main__':" in line:
                        in_main = True
                    
                    # If we hit a top-level def/class after __main__, we left the main block
                    if in_main and line.startswith(('def ', 'class ')):
                        in_main = False
                        
                    if not in_main and 'sys.exit(' in line and not line.strip().startswith('#'):
                        # Replace with raise RuntimeError
                        indent = len(line) - len(line.lstrip())
                        old_exit = line.strip()
                        # Try to extract the exit code or message
                        match = re.search(r'sys\.exit\((.*)\)', old_exit)
                        msg = match.group(1) if match else "1"
                        new_line = " " * indent + f'raise RuntimeError(f"Library code called sys.exit({msg})")'
                        lines[i] = new_line
                
                new_content = '\n'.join(lines)
                
                if new_content != original:
                    py_file.write_text(new_content)
                    print(f"  ✅ FIXED: {py_file.relative_to(ROOT)}")
                    self.fixes_applied += 1

    # --- PASS 2: AST ALIGNMENT MATRIX (HALLUCINATION DETECTOR) ---
    def pass2_alignment_matrix(self):
        print("\n" + "="*60)
        print("PASS 2: TEST-TO-IMPLEMENTATION ALIGNMENT MATRIX")
        print("="*60)
        
        # Build map of actual exports
        actual_exports = {}
        for d in TARGET_DIRS:
            for py_file in (ROOT / d).rglob("*.py"):
                if "__pycache__" in str(py_file) or py_file.name == "__init__.py": continue
                try:
                    tree = ast.parse(py_file.read_text())
                    # Collect top-level functions, classes, AND module-level variables
                    exports = set()
                    for node in ast.iter_child_nodes(tree):
                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                            exports.add(node.name)
                        elif isinstance(node, ast.Assign):
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    exports.add(target.id)
                    # Convert path to module name (e.g., engine/queue_manager.py -> engine.queue_manager)
                    mod_name = str(py_file.relative_to(ROOT)).replace('/', '.').replace('.py', '')
                    actual_exports[mod_name] = exports
                except SyntaxError:
                    pass

        # Check test imports
        test_dir = ROOT / "tests"
        for test_file in test_dir.glob("test_*.py"):
            try:
                tree = ast.parse(test_file.read_text())
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    mod_name = node.module
                    if mod_name not in actual_exports:
                        continue # Might be a stdlib or 3rd party module
                    
                    imported_names = [n.name for n in node.names]
                    for name in imported_names:
                        if name not in actual_exports[mod_name]:
                            # Hallucination detected! Find closest match
                            close = difflib.get_close_matches(name, actual_exports[mod_name], n=1, cutoff=0.6)
                            suggestion = f" (Did you mean: '{close[0]}'?)" if close else ""
                            issue = f"❌ {test_file.name} imports '{name}' from {mod_name}, but it doesn't exist.{suggestion}"
                            self.alignment_issues.append(issue)
                            print(f"  {issue}")

        if not self.alignment_issues:
            print("  ✅ All test imports perfectly align with implementation exports.")

    # --- PASS 3: PYTEST CATEGORIZER ---
    def pass3_pytest_categorizer(self):
        print("\n" + "="*60)
        print("PASS 3: PYTEST EXECUTION & ERROR CATEGORIZATION")
        print("="*60)
        
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60
        )
        
        output = result.stdout + result.stderr
        
        # Categorize errors
        categories = {
            "ImportError (Hallucinated Interface)": [],
            "AttributeError (Hallucinated Method)": [],
            "SystemExit (Rogue exit() call)": [],
            "Timeout/Hang (Unmocked heavy resource)": [],
            "AssertionError (Logic Bug)": [],
            "Other": []
        }
        
        for line in output.split('\n'):
            if 'FAILED' in line or 'ERROR' in line:
                if 'ImportError' in line or 'cannot import name' in line:
                    categories["ImportError (Hallucinated Interface)"].append(line.strip())
                elif 'AttributeError' in line:
                    categories["AttributeError (Hallucinated Method)"].append(line.strip())
                elif 'SystemExit' in line:
                    categories["SystemExit (Rogue exit() call)"].append(line.strip())
                elif 'AssertionError' in line or 'assert' in line:
                    categories["AssertionError (Logic Bug)"].append(line.strip())
                else:
                    categories["Other"].append(line.strip())

        for cat, errors in categories.items():
            if errors:
                print(f"\n  [{cat}] ({len(errors)} failures)")
                for e in errors[:5]: # Show first 5
                    print(f"    - {e[:120]}")

if __name__ == "__main__":
    auditor = Auditor()
    auditor.pass1_auto_fix()
    auditor.pass2_alignment_matrix()
    auditor.pass3_pytest_categorizer()
    
    print("\n" + "="*60)
    print(f"AUDIT COMPLETE. Auto-fixed {auditor.fixes_applied} files.")
    if auditor.alignment_issues:
        print(f"⚠️  WARNING: {len(auditor.alignment_issues)} hallucinated imports detected. See Pass 2.")
    print("="*60)
