"""
engine/consensus_gate.py
------------------------
Requires unanimous approval from two distinct heavy LLMs to promote an idea.
"""
import json
import logging
import re
from typing import Any, Dict, Tuple

from overnight.llm_client import generate, _call_gemini

logger = logging.getLogger(__name__)

# Matches a JSON object containing an "approve" key, even if surrounded by
# extraneous text (e.g. a model leaking Chain of Thought around the JSON).
_APPROVE_JSON_PATTERN = re.compile(
    r'\{\s*"approve"\s*:\s*(true|false)[^}]*\}',
    re.IGNORECASE | re.DOTALL,
)


def extract_json(text: str) -> Dict[str, Any]:
    """Extract a JSON voting object from the given text.

    The function searches for a JSON object containing an "approve" key
    and returns it as a Python dictionary. If no valid JSON is found,
    a default dictionary indicating failure is returned.

    Args:
        text: Raw text returned by an LLM, which may contain leaked
            Chain-of-Thought reasoning or Markdown around the JSON payload.

    Returns:
        A dictionary with at least an "approve" key. On parse failure,
        the returned dictionary indicates non-approval with a reason.

    Raises:
        Exception: Re-raised if a JSON-like block is found but fails to
            parse, after logging the failure for telemetry purposes.
    """
    if not text:
        return {"approve": False, "reason": "Empty response"}

    # 1. Hunt specifically for the voting JSON, even if buried in CoT rambling.
    match = _APPROVE_JSON_PATTERN.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception as exc:
            # HARDENED: Fail closed with telemetry.
            logger.error("CONTROL-PLANE FAILURE in consensus_gate.py: %s", exc)
            raise

    # 2. Fallback: find any top-level { ... } block.
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception as exc:
            # HARDENED: Fail closed with telemetry.
            logger.error("CONTROL-PLANE FAILURE in consensus_gate.py: %s", exc)
            raise

    return {"approve": False, "reason": "Failed to parse JSON (Model leaked Chain of Thought)"}


def get_consensus(
    proposal: str,
    api_keys: Dict[str, str],
) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:
    """Return consensus approval status and votes from two LLM judges.

    Args:
        proposal: The proposal text to evaluate.
        api_keys: Mapping of model names to API keys.

    Returns:
        A tuple containing:
            - bool: overall approval status (True only if both judges approve).
            - dict: vote from judge 1 (OpenRouter heavy model).
            - dict: vote from judge 2 (Gemini, called directly).

    Raises:
        ValueError: If the proposal contains prohibited characters.
    """
    # Input sanitization: reject proposals containing potentially dangerous characters.
    if any(bad in proposal for bad in (';', '--')):
        raise ValueError("Proposal contains prohibited characters")

    # GAG the models: forbid Chain of Thought and Markdown.
    prompt = (
        "You are a strict Staff Architect API endpoint. You do not speak. You only output JSON.\n"
        f"PROPOSAL:\n{proposal}\n\n"
        "Evaluate if this is safe and beneficial. "
        "CRITICAL: NO CHAIN OF THOUGHT. NO MARKDOWN. NO PROSE. "
        "Your very first character must be '{' and your last must be '}'.\n"
        "Format: {\"approve\": true, \"reason\": \"short explanation\"}"
    )

    # JUDGE 1: OpenRouter (heavy model).
    try:
        judge1_response = generate(prompt, api_keys, temperature=0.1, max_tokens=200)
        judge1_vote = extract_json(judge1_response)
    except Exception as exc:
        judge1_vote = {"approve": False, "reason": f"Judge 1 Error: {exc}"}

    # JUDGE 2: Gemini (direct).
    try:
        judge2_response = _call_gemini(prompt, api_keys.get("gemini"), max_tokens=200, temperature=0.1)
        judge2_vote = extract_json(judge2_response or "")
    except Exception as exc:
        judge2_vote = {"approve": False, "reason": f"Judge 2 Error: {exc}"}

    approved = judge1_vote.get("approve") is True and judge2_vote.get("approve") is True

    # Append-only audit trail: capture proposal, votes, and decision outcome.
    audit_log = (
        f"PROPOSAL: {proposal}\n"
        f"VOTE1: {json.dumps(judge1_vote, ensure_ascii=False)}\n"
        f"VOTE2: {json.dumps(judge2_vote, ensure_ascii=False)}\n"
        f"DECISION: {'APPROVED' if approved else 'REJECTED'}\n"
    )
    print(audit_log, flush=True)
    logger.info(audit_log)

    return approved, judge1_vote, judge2_vote
