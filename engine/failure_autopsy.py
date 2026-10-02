"""
engine/failure_autopsy.py
-------------------------
Analyzes a failed LLM output to generate a 2-sentence constraint for Attempt 2.
"""
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

# Ensure we can import from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from overnight.llm_client import generate as generate
except ImportError:
    generate: Optional[Callable[..., Optional[str]]] = None

AUTOPSY_PROMPT_TEMPLATE = (
    "You are a senior software architect performing a failure autopsy.\n"
    "An AI was asked to write a patch, but it produced invalid code.\n"
    "THE ERROR IT CAUSED:\n{error_message}\n\n"
    "THE BAD CODE IT WROTE:\n{bad_code}\n\n"
    "In exactly 2 sentences, explain the cognitive mistake the AI made.\n"
    "Focus on: Did it hallucinate API signatures? Did it ignore formatting rules? Did it break indentation?\n"
    "Output ONLY the 2 sentences. No markdown, no preamble."
)

# Truncation limits to keep the autopsy prompt within a reasonable token budget.
MAX_ERROR_MESSAGE_CHARS = 1500
MAX_BAD_CODE_CHARS = 2000

# LLM call parameters for the autopsy request.
AUTOPSY_TEMPERATURE = 0.1
AUTOPSY_MAX_TOKENS = 200

# Used when the LLM call is unavailable or fails, so the retry loop can still proceed.
FALLBACK_CONSTRAINT_MESSAGE = (
    "The previous attempt failed validation. Review the exact file contents "
    "and output format rules carefully."
)


def perform_autopsy(bad_code: str, error_message: str, api_keys: Dict[str, str]) -> str:
    """Analyze a failed LLM output and produce a short constraint for the next retry.

    Args:
        bad_code: The invalid code produced by the previous LLM attempt.
        error_message: The error/validation failure triggered by ``bad_code``.
        api_keys: Mapping of provider names to API keys, forwarded to ``generate``.

    Returns:
        A short (ideally 2-sentence) constraint describing the mistake, intended
        to be injected into the prompt for the next attempt. Falls back to a
        generic constraint message if the LLM call is unavailable or fails.
    """
    prompt = AUTOPSY_PROMPT_TEMPLATE.format(
        error_message=error_message[:MAX_ERROR_MESSAGE_CHARS],
        bad_code=bad_code[:MAX_BAD_CODE_CHARS],
    )

    if generate and api_keys:
        try:
            # Use the robust generate function which handles OpenRouter/Groq/Gemini fallbacks
            response_text = generate(
                prompt,
                api_keys,
                temperature=AUTOPSY_TEMPERATURE,
                max_tokens=AUTOPSY_MAX_TOKENS,
            )
            if response_text:
                return response_text.strip().replace('\n', ' ')
        except Exception as e:
            print(f"       ⚠️ Autopsy LLM call failed: {e}")

    # Safe fallback that doesn't break the loop but signals it's a fallback
    return FALLBACK_CONSTRAINT_MESSAGE
