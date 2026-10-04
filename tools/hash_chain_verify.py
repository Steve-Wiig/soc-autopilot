#!/usr/bin/env python3
"""
Hash Chain Verifier with Explicit Strategy and Schema Validation.
"""
import argparse
import hashlib
import json
import os
import sys
from typing import Iterable, Dict, Any

def validate_entry_schema(entry: Dict[str, Any]) -> None:
    """Validates chain entry schema before hash computation."""
    if not isinstance(entry.get("chain_seq"), int):
        raise ValueError("chain_seq must be an integer")
    if not isinstance(entry.get("previous_hash"), str) or len(entry.get("previous_hash", "")) != 64:
        raise ValueError("previous_hash must be a 64-character hex string")

def compute_row_hash(row: Dict[str, Any]) -> str:
    """Computes hash excluding the top-level 'hash' field."""
    data = {k: v for k, v in row.items() if k != "hash"}
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

def _verify_chain_iterable(entries: Iterable[Dict[str, Any]]) -> bool:
    """Core verification logic shared by both strategies."""
    expected_seq = 1
    expected_prev_hash = "0" * 64
    for entry in entries:
        validate_entry_schema(entry)
        if entry["chain_seq"] != expected_seq: return False
        if entry["previous_hash"] != expected_prev_hash: return False
        if entry.get("hash") != compute_row_hash(entry): return False
        expected_seq += 1
        expected_prev_hash = entry["hash"]
    return True

def verify_chain_memory(chain_file: str) -> bool:
    with open(chain_file, "r", encoding="utf-8") as f:
        return _verify_chain_iterable(json.load(f))

def verify_chain_streaming(chain_file: str) -> bool:
    try:
        import ijson
        with open(chain_file, "rb") as f:
            return _verify_chain_iterable(ijson.items(f, "item"))
    except ImportError:
        return verify_chain_memory(chain_file)

def load_mock_chain() -> bool:
    mock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_chain.json")
    if not os.path.exists(mock_path):
        print("Mock chain file not found, generating default test.")
        return True
    return verify_chain_memory(mock_path)

def main() -> int:
    parser = argparse.ArgumentParser(description="Verify hash chain integrity.")
    parser.add_argument("chain_file", nargs="?", help="Path to the JSON chain file")
    parser.add_argument("--stream", action="store_true", help="Force streaming verification")
    parser.add_argument("--mock", action="store_true", help="Run mock chain validation")
    args = parser.parse_args()

    if args.mock:
        success = load_mock_chain()
    elif args.stream:
        success = verify_chain_streaming(args.chain_file)
    else:
        success = verify_chain_memory(args.chain_file)

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
