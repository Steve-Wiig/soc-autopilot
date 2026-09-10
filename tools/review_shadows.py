#!/usr/bin/env python3
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

def run(cmd):
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT)
    return res.stdout.strip(), res.returncode

def main():
    print("\n🔍 Fetching pending AI patches from GitHub...")
    run("git fetch origin")
    
    out, _ = run("git branch -r | grep 'origin/shadow/autofix'")
    if not out:
        print("✅ No pending shadow branches. The AI hasn't generated any new patches today.")
        return
        
    branches = [b.strip().replace('origin/', '') for b in out.split('\n') if b.strip()]
    print(f"📦 Found {len(branches)} pending patches for your review.\n")
    
    base, _ = run("git branch --show-current")
    if not base: base = "main"
    
    for i, branch in enumerate(branches, 1):
        print("="*70)
        print(f"  🔎 REVIEW [{i}/{len(branches)}]: {branch}")
        print("="*70)
        
        msg, _ = run(f"git log origin/{branch} -1 --pretty=%B")
        print(f"📝 WHAT IS IT TRYING TO FIX?")
        print(f"   {msg}\n")
        
        files, _ = run(f"git diff --name-only origin/{base}...origin/{branch}")
        print(f"📂 FILES CHANGED (Blast Radius):")
        if files:
            for f in files.split('\n'): print(f"   - {f}")
        print()
        
        stats, _ = run(f"git diff origin/{base}...origin/{branch} --stat")
        print(f"📊 CHURN (Lines added/removed):")
        print(f"   {stats}\n")
        
        print("ACTIONS:")
        print("  [W] Web Review (Open GitHub to see highlighted code diff)")
        print("  [A] Approve & Merge (Apply to your live codebase)")
        print("  [R] Reject & Delete (Throw it away)")
        print("  [S] Skip (Leave for later)")
        print("  [Q] Quit")
        
        while True:
            choice = input("\nChoose action [W/A/R/S/Q]: ").strip().upper()
            
            if choice == 'W':
                url = f"https://github.com/Steve-Wiig/soc-autopilot/compare/{base}...{branch}"
                print(f"🌐 Opening: {url}")
                for cmd in ["xdg-open", "open", "start"]:
                    if subprocess.run([cmd, url], capture_output=True).returncode == 0:
                        break
                input("Press Enter when done reviewing in browser...")
                
            elif choice == 'A':
                print("✅ Approving and merging...")
                run(f"git checkout {base}")
                run(f"git merge origin/{branch}")
                run(f"git push origin {base}")
                run(f"git push origin --delete {branch}")
                print("🎉 Merged into live codebase!")
                break
                
            elif choice == 'R':
                print("🗑️ Rejecting and deleting branch...")
                run(f"git push origin --delete {branch}")
                print("Deleted.")
                break
                
            elif choice == 'S':
                print("Skipped.")
                break
                
            elif choice == 'Q':
                sys.exit(0)
                
            else:
                print("Invalid choice.")
                
    print("\n✅ All done. You're caught up.")

if __name__ == "__main__":
    main()
