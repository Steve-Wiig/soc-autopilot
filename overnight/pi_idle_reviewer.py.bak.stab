#!/usr/bin/env python3
"""
Idle Reviewer: When Pi Critic has no new jobs, review historical patches.
This maximizes Pi utilization without blocking the main pipeline.
"""
import json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def main():
    print("🍓 Pi Idle Reviewer started. Checking for historical patches...")
    
    while True:
        # Check if there are unreviewed patches in pi_patches.jsonl
        patches_file = ROOT / 'overnight' / 'pi_patches.jsonl'
        reviewed_file = ROOT / 'overnight' / 'pi_reviewed.jsonl'
        
        if not patches_file.exists():
            time.sleep(300)
            continue
        
        # Get all patches
        patches = []
        for line in patches_file.read_text().strip().split('\n'):
            if line.strip():
                try:
                    patches.append(json.loads(line))
                except:
                    pass
        
        # Get already reviewed
        reviewed = set()
        if reviewed_file.exists():
            for line in reviewed_file.read_text().strip().split('\n'):
                if line.strip():
                    try:
                        entry = json.loads(line)
                        reviewed.add((entry['file'], entry['timestamp']))
                    except:
                        pass
        
        # Find unreviewed patches
        unreviewed = [p for p in patches if (p['file'], p['timestamp']) not in reviewed]
        
        if unreviewed:
            print(f"📥 Found {len(unreviewed)} unreviewed patches. Reviewing...")
            # Submit to Redis for Critic to review
            try:
                import redis
                r = redis.Redis(host='192.168.1.31', port=6379, db=0, decode_responses=True)
                for patch in unreviewed[:5]:  # Batch 5 at a time
                    job_id = f"review_{int(time.time())}_{patch['file'].replace('/', '_')}"
                    # Read original file content
                    original_content = ""
                    full_path = ROOT / patch['file']
                    if full_path.exists():
                        original_content = full_path.read_text()
                    
                    job_data = {
                        'job_id': job_id,
                        'file': patch['file'],
                        'original': original_content,  # Original file content
                        'patch': patch['patch'],
                        'issue': patch['issue'].get('description', ''),
                        'timestamp': time.time()
                    }
                    r.lpush('pi_critic_queue', json.dumps(job_data))
                    
                    # Mark as reviewed
                    with open(reviewed_file, 'a') as f:
                        f.write(json.dumps({'file': patch['file'], 'timestamp': patch['timestamp']}) + '\n')
                    
                    print(f"    🍓 Submitted historical patch for review: {patch['file']}")
                    time.sleep(10)  # Pace submissions
            except Exception as e:
                print(f"⚠️ Could not submit to Redis: {e}")
        
        # Check every 5 minutes
        time.sleep(300)

if __name__ == "__main__":
    main()
