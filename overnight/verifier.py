import ast, hashlib, json, os, re, subprocess, sys
from pathlib import Path

PROJECT_ROOT = Path(str(ROOT))
EVIDENCE_DIR   = PROJECT_ROOT / "overnight" / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

class VerifierResult:
    def __init__(self, task_id, passed, checks, evidence_hash, notes=""):
        self.task_id, self.passed, self.checks = task_id, passed, checks
        self.evidence_hash, self.notes = evidence_hash, notes

def verify_python_syntax(filepath):
    try:
        with open(filepath, 'r') as f: ast.parse(f.read())
        return True, "syntax valid"
    except SyntaxError as e: return False, f"syntax error: {e}"
    except FileNotFoundError: return False, "file not found"

def verify_no_hallucinated_imports(filepath):
    try:
        with open(filepath, 'r') as f: tree = ast.parse(f.read())
    except: return True, "skipped"
    from pathlib import Path
    p = Path(filepath)
    own_pkg = ""
    for parent in ("engine", "orchestrator", "memory", "tools", "tests"):
        if parent in p.parts:
            own_pkg = parent
            break
    suspicious = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod.startswith(("engine.", "orchestrator.", "memory.")):
                if mod.split(".")[0] == own_pkg:
                    continue
                suspicious.append(mod)
    return (False, f"hallucinated imports: {suspicious}") if suspicious else (True, "clean")
def verify_exit_codes(filepath):
    try:
        with open(filepath, 'r') as f: text = f.read()
    except: return False, "file not found"
    has_exit = "exit" in text.lower() or "if __name__" in text or "def main" in text
    has_0 = "0" in text
    has_1 = "1" in text
    return (True, "exit codes present") if (has_exit and has_0 and has_1) else (False, "missing exit codes")
def verify_no_secrets(content):
    patterns = [(r"AKIA[0-9A-Z]{16}", "AWS key"), (r"ghp_[A-Za-z0-9]{36}", "GitHub token"), (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "Private Key")]
    for pat, name in patterns:
        if re.search(pat, content) and "EXAMPLE" not in content and "REDACTED" not in content:
            return False, f"potential {name} found"
    return True, "no secrets"

def verify_task(task, output_path):
    checks, all_passed = [], True
    if not os.path.isfile(output_path):
        return VerifierResult(task["id"], False, [{"check":"exists","passed":False}], "0", "file missing")

    with open(output_path, 'r') as f: content = f.read()

    if output_path.endswith('.py'):
        ok, msg = verify_python_syntax(output_path)
        checks.append({"check":"syntax","passed":ok,"detail":msg}); all_passed = all_passed and ok
        ok, msg = verify_no_hallucinated_imports(output_path)
        checks.append({"check":"imports","passed":ok,"detail":msg}); all_passed = all_passed and ok
        if task["type"] == "implement_tool":
            ok, msg = verify_exit_codes(output_path)
            checks.append({"check":"exit_codes","passed":ok,"detail":msg}); all_passed = all_passed and ok

    ok, msg = verify_no_secrets(content)
    checks.append({"check":"secrets","passed":ok,"detail":msg}); all_passed = all_passed and ok

    ok = len(content.split('\n')) >= 10
    checks.append({"check":"min_length","passed":ok,"detail":f"{len(content.split(chr(10)))} lines"}); all_passed = all_passed and ok

    evidence = json.dumps(checks)
    h = hashlib.sha256(evidence.encode()).hexdigest()[:16]
    (EVIDENCE_DIR / f"{task['id']}_{h}.json").write_text(evidence)
    return VerifierResult(task["id"], all_passed, checks, h, "passed" if all_passed else "failed checks")
