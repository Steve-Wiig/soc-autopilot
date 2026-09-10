"""
engine/consensus_gate.py
------------------------
Requires unanimous approval from two distinct heavy LLMs to promote an idea.
"""
import json
import re
from overnight.llm_client import generate, _call_gemini

def extract_json(text: str) -> dict:
    """Extract a JSON object from the given text.

    The function searches for a JSON object containing an "approve" key
    and returns it as a Python dictionary. If no valid JSON is found,
    a default dictionary indicating failure is returned.
    """
    if not text: return {"approve": False, "reason": "Empty response"}
    
    # 1. Hunt specifically for the voting JSON, even if buried in CoT rambling
    match = re.search(r'\{\s*"approve"\s*:\s*(true|false)[^}]*\}', text, re.IGNORECASE | re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass

    # 2. Fallback: Find any { ... } block
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try: return json.loads(text[start:end+1])
        except: pass

    return {"approve": False, "reason": "Failed to parse JSON (Model leaked Chain of Thought)"}

def get_consensus(proposal: str, api_keys: dict) -> tuple:
    """Return consensus approval status and votes from two LLM judges.

    Parameters
    ----------
    proposal : str
        The proposal text to evaluate.
    api_keys : dict
        Mapping of model names to API keys.

    Returns
    -------
    tuple
        A tuple containing:
        - bool: overall approval status
        - dict: vote from judge 1
        - dict: vote from judge 2
    """
    # Import inside function to avoid import‑time side effects
    from overnight.llm_client import generate, _call_gemini

    # Input sanitization: reject proposals containing potentially dangerous characters
    if any(bad in proposal for bad in (';', '--')):
        raise ValueError("Proposal contains prohibited characters")

    # GAG the models: Forbid Chain of Thought and Markdown
    prompt = (
        "You are a strict Staff Architect API endpoint. You do not speak. You only output JSON.\n"
        f"PROPOSAL:\n{proposal}\n\n"
        "Evaluate if this is safe and beneficial. "
        "CRITICAL: NO CHAIN OF THOUGHT. NO MARKDOWN. NO PROSE. "
        "Your very first character must be '{' and your last must be '}'.\n"
        "Format: {\"approve\": true, \"reason\": \"short explanation\"}"
    )
    
    # JUDGE 1: OpenRouter (Heavy Model)
    try:
        raw1 = generate(prompt, api_keys, temperature=0.1, max_tokens=200)
        vote1 = extract_json(raw1)
    except Exception as e:
        vote1 = {"approve": False, "reason": f"Judge 1 Error: {e}"}
        
    # JUDGE 2: Gemini (Direct)
    try:
        raw2 = _call_gemini(prompt, api_keys.get("gemini"), max_tokens=200, temperature=0.1)
        vote2 = extract_json(raw2 or "")
    except Exception as e:
        vote2 = {"approve": False, "reason": f"Judge 2 Error: {e}"}
        
    approved = vote1.get("approve") is True and vote2.get("approve") is True
    # Append‑only audit logging: capture proposal, votes, and decision outcome
    audit_log = (
        f"PROPOSAL: {proposal}\n"
        f"VOTE1: {json.dumps(vote1, ensure_ascii=False)}\n"
        f"VOTE2: {json.dumps(vote2, ensure_ascii=False)}\n"
        f"DECISION: {'APPROVED' if approved else 'REJECTED'}\n"
    )
    return approved, vote1, vote2
