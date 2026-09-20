#!/usr/bin/env python3
"""
Batch Orchestrator for Aider.
Reads tasks from a JSON file and runs aider headlessly.
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

def run_batch(tasks_file: str, model: str, timeout: int = 300):
    path = Path(tasks_file)
    if not path.exists():
        print(f"❌ Task file not found: {tasks_file}")
        return

    tasks = json.loads(path.read_text())
    print(f"🚀 Starting batch run: {len(tasks)} tasks | Model: {model}")
    print("="*60)

    results = []
    
    for i, task in enumerate(tasks, 1):
        target_file = task.get("file")
        prompt = task.get("prompt")
        
        if not target_file or not prompt:
            print(f"⚠️  Skipping malformed task {i}")
            continue
            
        print(f"\n[{i}/{len(tasks)}] 📝 Processing: {target_file}")
        print(f"   Task: {prompt[:80]}...")
        
        # Construct the headless aider command
        cmd = [
            "aider", target_file,
            "--message", prompt,
            "--yes",               # Auto-accept changes
            "--no-auto-commits",   # We will handle git manually or in a wrapper
            "--model", model,
            "--dark-mode",          # Cleaner logs
            "--no-show-model-warnings"
        ]
        
        start_time = datetime.now()
        try:
            # Run aider headlessly
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=Path(__file__).resolve().parent.parent
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            if result.returncode == 0:
                print(f"✅ SUCCESS ({duration:.1f}s)")
                results.append({"file": target_file, "status": "SUCCESS", "duration": duration})
            else:
                print(f"❌ FAILED ({duration:.1f}s)")
                # Print the last few lines of stderr to see why it failed
                print("   Error:", "\n   ".join(result.stderr.strip().split("\n")[-3:]))
                results.append({"file": target_file, "status": "FAILED", "duration": duration, "error": result.stderr[-500:]})
                
        except subprocess.TimeoutExpired:
            print(f"⏱️  TIMEOUT after {timeout}s")
            results.append({"file": target_file, "status": "TIMEOUT", "duration": timeout})
        except Exception as e:
            print(f"💥 CRASH: {e}")
            results.append({"file": target_file, "status": "CRASH", "error": str(e)})

    # Save the batch report
    report_path = Path("overnight") / f"batch_aider_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(results, indent=2))
    print("\n" + "="*60)
    print(f"🏁 Batch complete. Report saved to: {report_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch run aider tasks.")
    parser.add_argument("--tasks", default="overnight/batch_tasks.json", help="Path to tasks JSON")
    parser.add_argument("--model", default="openrouter/qwen/qwen-2.5-coder-32b-instruct:free", help="Model to use")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per task in seconds")
    args = parser.parse_args()
    
    run_batch(args.tasks, args.model, args.timeout)
