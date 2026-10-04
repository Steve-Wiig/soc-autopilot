"""
simulator/mock_openrouter.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Mock LLM API compatible with OpenRouter's API format.

Returns deterministic, pre-canned JSON responses for specific prompts,
allowing pipeline testing without API quota consumption.

Supported prompt patterns (case-insensitive):
  - "classify this issue"  -> returns a classification JSON
  - "summarize this log"   -> returns a summary JSON
  - "generate fix"         -> returns a remediation JSON
  - any other prompt       -> returns a generic helpful response

Usage:
  uvicorn simulator.mock_openrouter:app --reload --port 8001

The server will be available at http://127.0.0.1:8001
API format matches OpenRouter: POST /v1/chat/completions
"""

import json
import random
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

app = FastAPI(title="Mock OpenRouter API", version="1.0.0")

# Canned responses keyed by prompt category
CANNED_RESPONSES = {
    "classify": {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "classification": "critical",
                        "reason": "Issue involves credential exposure and lateral movement potential.",
                        "action": "Immediate isolation and credential rotation required."
                    })
                },
                "finish_reason": "stop",
            }
        ]
    },
    "summarize": {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "summary": "User reported unauthorized login from external IP during off-hours. Multiple failed attempts observed.",
                        "key_indicators": ["failed_ssh", "off_hours", "external_ip"]
                    })
                },
                "finish_reason": "stop",
            }
        ]
    },
    "generate_fix": {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "fix": "Apply patch XYZ-1234, rotate compromised keys, and enforce MFA for all privileged accounts.",
                        "steps": [
                            "Run install_patch.sh",
                            "Rotate API keys in vault",
                            "Enable MFA for admin accounts"
                        ]
                    })
                },
                "finish_reason": "stop",
            }
        ]
    },
}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.0
    max_tokens: Optional[int] = 500


@app.post("/v1/chat/completions")
def chat_completion(request: ChatCompletionRequest):
    # Determine response based on prompt content
    last_user_msg = ""
    for msg in request.messages:
        if msg.role == "user":
            last_user_msg = msg.content.lower()

    # Simple keyword matching for demo purposes
    if "classify" in last_user_msg or "classify this" in last_user_msg:
        return CANNED_RESPONSES["classify"]
    elif "summarize" in last_user_msg or "summary" in last_user_msg:
        return CANNED_RESPONSES["summarize"]
    elif "fix" in last_user_msg or "generate fix" in last_user_msg or "remediate" in last_user_msg:
        return CANNED_RESPONSES["generate_fix"]
    else:
        # Generic deterministic response
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({
                            "note": "This is a deterministic mock response.",
                            "suggestion": "Provide more context for a targeted mock response."
                        })
                    },
                    "finish_reason": "stop",
                }
            ]
        }


@app.get("/")
def root():
    return {"message": "Mock OpenRouter API is running", "endpoint": "POST /v1/chat/completions"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
