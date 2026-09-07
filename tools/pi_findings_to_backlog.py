#!/usr/bin/env python3
"""
Optimized Bridge: Reads from a dedicated pending file instead of 
re-scanning the entire telemetry buffer every hour.
"""
import json, fcntl, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
BACKLOG_FILE = ROOT / "overnight" / "fix_backlog.json"
PENDING_FILE = ROOT / "runtime" / "analysis" / "pi_findings_pending.jsonl"

def load_backlog():
    if not BACKLOG_FILE.exists(): return []
    try: 
        with open(BACKLOG_FILE, 'r') as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except (json.JSONDecodeError, OSError): return []

def save_backlog(backlog):
    with open(BACKLOG_FILE, 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(backlog, f, indent=2)
        fcntl.flock(f, fcntl.LOCK_UN)

def parse_nested_json(raw_str):
    if isinstance(raw_str, dict): return raw_str
    if isinstance(raw_str, str):
        try: return json.loads(raw_str)
        except json.JSONDecodeError: return {}
    return {}

def process_pending():
    if not PENDING_FILE.exists():
        print("ℹ️ No pending Pi findings.")
        return

    backlog = load_backlog()
    existing_items = {f"{item['file']}::{item['issue']['description'][:80]}" for item in backlog}
    new_findings_count = 0

    # Atomically rename to prevent race conditions with the ingestor
    temp_path = PENDING_FILE.with_suffix(".processing")
    try:
        PENDING_FILE.rename(temp_path)
    except FileNotFoundError:
        return

    try:
        with temp_path.open('r') as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                findings_raw = event.get("payload", {}).get("findings", {})
                for tool_name in ["pylint", "bandit"]:
                    tool_data = parse_nested_json(findings_raw.get(tool_name, "{}"))
                    issues = tool_data.get("issues", [])
                    
                    for issue in issues:
                        file_path = issue.get("file")
                        line_num = issue.get("line", 0)
                        issue_code = issue.get("issue", "Unknown")
                        description = issue.get("description", issue.get("fix", f"{tool_name} issue {issue_code}"))
                        suggestion = issue.get("fix", f"Resolve {tool_name} {issue_code} warning.")
                        
                        dedup_key = f"{file_path}::{description[:80]}"
                        if dedup_key in existing_items: continue
                            
                        backlog_item = {
                            "file": file_path,
                            "issue": {
                                "category": "blueprint_compliance" if tool_name == "bandit" else "maintainability",
                                "severity": "medium",
                                "line_start": line_num,
                                "line_end": line_num,
                                "description": f"[{tool_name.upper()} {issue_code}] {description}",
                                "suggestion": suggestion,
                                "impact": "low",
                                "effort": "trivial"
                            },
                            "attempts": 0,
                            "source": "pi_edge_bandit"
                        }
                        backlog.append(backlog_item)
                        existing_items.add(dedup_key)
                        new_findings_count += 1
    except Exception as e:
        print(f"Error processing pending file: {e}", file=sys.stderr)
    finally:
        temp_path.unlink(missing_ok=True)

    if new_findings_count > 0:
        save_backlog(backlog)
        print(f"✅ Injected {new_findings_count} new Pi findings into fix_backlog.json")
    else:
        print("ℹ️ No new unique findings to inject.")

if __name__ == "__main__":
    process_pending()
