#!/usr/bin/env python3
"""
Lightweight AST Dependency Mapper.
Scans the codebase to find exactly which files import from a target module.
"""
import ast
import os
import sys
from pathlib import Path

def get_module_name(filepath: Path) -> str:
    """Convert a file path to a Python module path (e.g., engine/cer_critic.py -> engine.cer_critic)"""
    rel = filepath.relative_to(Path.cwd())
    return str(rel.with_suffix("")).replace(os.sep, ".")

def find_dependents(target_file: str) -> list[str]:
    """Find all files that import from the target_file."""
    target_path = Path(target_file).resolve()
    target_module = get_module_name(target_path)
    target_base = target_path.stem
    
    dependents = []
    
    # Scan all Python files in the project
    for root, _, files in os.walk("."):
        if "__pycache__" in root or ".git" in root or "tests" in root:
            continue
            
        for file in files:
            if not file.endswith(".py"):
                continue
                
            filepath = Path(root) / file
            if filepath.resolve() == target_path:
                continue
                
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=filepath)
            except Exception:
                continue
                
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and (node.module == target_module or node.module.endswith(f".{target_base}")):
                        dependents.append(str(filepath))
                        break
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == target_module or alias.name == target_base:
                            dependents.append(str(filepath))
                            break
                            
    return dependents

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 tools/dependency_mapper.py <target_file.py>")
        sys.exit(1)
        
    deps = find_dependents(sys.argv[1])
    if deps:
        print("DEPENDENTS_FOUND:")
        for d in deps:
            print(f" - {d}")
    else:
        print("NO_DEPENDENTS")
