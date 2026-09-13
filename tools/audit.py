#!/usr/bin/env python3
"""
CLI tool to query the LLM Reasoning Ledger (Black Box).
Reads from the local buffer. NAS was intentionally removed in P1-4.
"""
import json
import argparse
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOCAL_FILE = ROOT / "overnight" / ".reasoning_buffer" / "current.jsonl"

def get_ledger_path():
    # Local-only after NAS removal (P1-4).
    return LOCAL_FILE

def main():
    parser = argparse.ArgumentParser(description="Audit the LLM Reasoning Ledger")
    parser.add_argument("--last", type=int, default=10, help="Show last N interactions")
    parser.add_argument("--stage", type=str, help="Filter by stage (e.g., 'tdd', 'heavy')")
    args = parser.parse_args()

    ledger = get_ledger_path()
    if not ledger.exists():
        print("⚠️ Ledger is empty.")
        return

    events = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    if args.stage:
        events = [e for e in events if args.stage.lower() in e.get("stage", "").lower()]
    
    print(f"📂 Reading from: {ledger}")
    for e in events[-args.last:]:
        print(f"\n{'='*60}")
        print(f"[{e.get('stage', 'unknown').upper()}] Model: {e.get('model', 'unknown')}")
        print(f"Prompt ({e.get('prompt_chars')} chars):")
        print(e.get('prompt_preview', 'No preview'))
        print(f"\nResponse ({e.get('response_chars')} chars):")
        print(e.get('response_preview', 'No preview'))
        print(f"{'='*60}")

if __name__ == "__main__":
    main()
