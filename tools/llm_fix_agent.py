#!/usr/bin/env python3
import ast, json, re, sys
from pathlib import Path
from typing import Dict, Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def _looks_like_reasoning(text: str) -> bool:
    markers = [r"let's think step by step", r"first,? i will", r"my thought process", r"reasoning:", r"wait,? no,"]
    return any(re.search(m, text.lower()) for m in markers)

def _validate_ast(patch_content: str) -> bool:
    try:
        if "```python" in patch_content:
            for block in re.findall(r"```python\n(.*?)```", patch_content, re.DOTALL): ast.parse(block)
        else:
            ast.parse(patch_content)
        return True
    except SyntaxError:
        return False

def request_fix(failure_context: Dict[str, Any]) -> Dict[str, Any]:
    # Mocking the LLM response for structural validation
    raw_response = failure_context.get("mock_llm_response", "def dummy_fix():\n    return True")

    if _looks_like_reasoning(raw_response):
        return {"severity": "medium", "cause": "reasoning_leakage_detected", "suggested_fix": "", "confidence": 0.0, "requires_human_review": True}
    if not _validate_ast(raw_response):
        return {"severity": "medium", "cause": "ast_validation_failed", "suggested_fix": raw_response, "confidence": 0.2, "requires_human_review": True}

    return {"severity": "low", "cause": "automated_fix_generated", "suggested_fix": raw_response, "confidence": 0.85, "requires_human_review": True}

if __name__ == "__main__":
    print(json.dumps(request_fix({"mock_llm_response": "def safe():\n    pass"}), indent=2))
