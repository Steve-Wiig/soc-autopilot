#!/usr/bin/env python3
import json, time, fcntl, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCHES_FILE = ROOT / 'overnight' / 'pi_patches.jsonl'
ARCHIVED_FILE = ROOT / 'overnight' / 'pi_patches.archived.jsonl'

def get_deterministic_job_id(patch_dict):
    raw = f"{patch_dict.get('timestamp')}::{patch_dict.get('file')}::{patch_dict.get('patch')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def process_patch(patch_dict, patch_json_str):
    try:
        import redis
        r = redis.Redis(host='192.168.1.31', port=6379, db=0, decode_responses=True)
        job_id = get_deterministic_job_id(patch_dict)
        full_path = ROOT / patch_dict['file']
        original_content = full_path.read_text() if full_path.exists() else ""
        job_data = {
            'job_id': job_id, 'file': patch_dict['file'], 'original': original_content,
            'patch': patch_dict['patch'], 'issue': patch_dict['issue'].get('description', ''), 'timestamp': time.time()
        }
        r.lpush('pi_critic_queue', json.dumps(job_data))
        with open(PATCHES_FILE, 'r+') as f_active, open(ARCHIVED_FILE, 'a') as f_archived:
            fcntl.flock(f_active, fcntl.LOCK_EX)
            try:
                lines = f_active.readlines()
                new_lines = []
                moved = False
                target_hash = hashlib.md5(patch_json_str.encode()).hexdigest()
                for line in lines:
                    if not line.strip(): continue
                    line_hash = hashlib.md5(line.encode()).hexdigest()
                    if line_hash == target_hash and not moved:
                        f_archived.write(line)
                        moved = True
                    else:
                        new_lines.append(line)
                if moved:
                    f_active.seek(0)
                    f_active.truncate()
                    f_active.writelines(new_lines)
                    print(f"    🍓 Submitted and archived: {patch_dict['file']}")
                    return True
            finally:
                fcntl.flock(f_active, fcntl.LOCK_UN)
    except Exception as e:
        print(f"⚠️ Could not submit to Redis: {e}")
    return False

def main():
    print("🍓 Pi Idle Reviewer started.")
    while True:
        if not PATCHES_FILE.exists():
            time.sleep(300); continue
        patches = []
        with open(PATCHES_FILE, 'r') as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                for line in f:
                    if line.strip():
                        try: patches.append((json.loads(line), line))
                        except: pass
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        if patches:
            print(f"📥 Found {len(patches)} active patches. Handing off to Critic...")
            for patch_dict, patch_json_str in patches[:5]:
                if process_patch(patch_dict, patch_json_str): time.sleep(5)
        time.sleep(300)

if __name__ == "__main__":
    main()
