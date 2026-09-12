#!/usr/bin/env python3
"""
Async Pi Generator Worker
Generates patches via Ollama and stores them in pi_patches.jsonl.
Tracks failed attempts to prevent infinite loops.
"""
import json, requests, time
from pathlib import Path
from datetime import datetime

OLLAMA_URL = "http://192.168.1.31:11434"
MODEL = "qwen2.5-coder:3b"
ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / "overnight" / "fix_backlog.json"
PI_PATCHES = ROOT / "overnight" / "pi_patches.jsonl"
ATTEMPTED_FILE = ROOT / "overnight" / "pi_attempted.json"
MAX_ATTEMPTS_PER_ITEM = 3  # After 3 failures, permanently skip

def load_attempted():
    """Load attempted items with their failure counts."""
    if not ATTEMPTED_FILE.exists():
        return {}
    try:
        data = json.loads(ATTEMPTED_FILE.read_text())
        # Convert list format (old) to dict format if needed
        if isinstance(data, list):
            return {item: 1 for item in data}
        return data
    except Exception:
        return {}

def mark_attempted(key):
    """Record a failed attempt for this item."""
    attempted = load_attempted()
    attempted[key] = attempted.get(key, 0) + 1
    ATTEMPTED_FILE.write_text(json.dumps(attempted))
    count = attempted[key]
    if count >= MAX_ATTEMPTS_PER_ITEM:
        print(f"    🚫 Permanently skipping after {count} failed attempts: {key}")
    else:
        print(f"    ⚠️ Attempt {count}/{MAX_ATTEMPTS_PER_ITEM} failed: {key}")

def get_generated():
    """Get set of (file, description) tuples that have successful patches."""
    if not PI_PATCHES.exists():
        return set()
    generated = set()
    for line in PI_PATCHES.read_text().strip().split('\n'):
        if line.strip():
            try:
                entry = json.loads(line)
                generated.add((entry['file'], entry['issue']['description']))
            except Exception:
                pass
    return generated

def generate_patch(file_path, issue):
    """Ask the Pi to generate a patch."""
    full_path = ROOT / file_path
    if not full_path.exists():
        return None
    
    source = full_path.read_text()
    
    prompt = f"""You are a strict Python engineer. Fix this issue safely.

RULES:
1. Output ONLY a unified diff patch. No markdown backticks, no explanations.
2. DO NOT hallucinate imports, functions, or variables. Use ONLY what exists in the FILE.
3. If you cannot fix this safely without guessing, output exactly: NO_SAFE_FIX_AVAILABLE
4. Keep the patch minimal - change only what is necessary.

CATEGORY: {issue.get('category', 'unknown')}
DESCRIPTION: {issue.get('description', 'unknown')}
SUGGESTION: {issue.get('suggestion', 'none')}

FILE CONTENT:
{source[:6000]}

UNIFIED DIFF FORMAT:
--- a/{file_path}
+++ b/{file_path}
@@ -old,+new @@
-old line
+new line
"""
    
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 1024}
        }, timeout=120)
        
        if resp.status_code == 200:
            content = resp.json().get("response", "").strip()
            # Clean up markdown code fences if present
            if content.startswith("```"):
                lines = content.split('\n')
                content = '\n'.join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            if content and "NO_SAFE_FIX_AVAILABLE" not in content:
                return content
    except requests.exceptions.Timeout:
        print(f"  ⏱️ Pi generation timed out for {file_path}")
    except Exception as e:
        print(f"  ❌ Pi unreachable: {e}")
    
    return None


def load_backlog():
    if not BACKLOG.exists(): return []
    try:
        with open(BACKLOG, 'r') as f:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except (json.JSONDecodeError, OSError):
        return []

def main():
    print("🍓 Pi Generator Worker started. Polling backlog...")
    cycle = 0
    
    while True:
        try:
            cycle += 1
            
            if not BACKLOG.exists():
                print(f"  [cycle {cycle}] No backlog yet, waiting...")
                time.sleep(60)
                continue
            
            backlog = load_backlog()
            generated = get_generated()
            attempted = load_attempted()
            
            # Filter: not already generated AND not permanently failed
            pending = []
            for item in backlog:
                key = f"{item['file']}::{item['issue']['description'][:80]}"
                if (item['file'], item['issue']['description']) in generated:
                    continue  # Already have a patch for this
                if attempted.get(key, 0) >= MAX_ATTEMPTS_PER_ITEM:
                    continue  # Permanently skipped
                pending.append((item, key))
            
            if not pending:
                if cycle % 10 == 1:  # Only print every 10th cycle to reduce noise
                    print(f"  [cycle {cycle}] All {len(backlog)} items processed or skipped. Waiting 5min...")
                time.sleep(300)
                continue
            
            item, key = pending[0]
            file_path = item['file']
            issue = item['issue']
            
            print(f"📥 [{len(pending)} pending] Generating patch for {file_path} ({issue.get('category')})...")
            start = time.time()
            
            patch = generate_patch(file_path, issue)
            elapsed = time.time() - start
            
            if patch:
                entry = {
                    'timestamp': datetime.now().isoformat(),
                    'file': file_path,
                    'issue': issue,
                    'patch': patch,
                    'generation_time': elapsed
                }
                with open(PI_PATCHES, 'a') as f:
                    f.write(json.dumps(entry) + '\n')
                print(f"✅ Generated patch for {file_path} ({elapsed:.0f}s, {len(patch)} chars)")
            else:
                mark_attempted(key)
            
            # Brief pause between generations to let Pi recover
            time.sleep(15)
            
        except KeyboardInterrupt:
            print("\n🛑 Generator stopped")
            break
        except Exception as e:
            print(f"❌ Generator error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
