import json
from pathlib import Path
from datetime import datetime



def main():
    ROOT = Path(__file__).resolve().parent.parent
    prog = json.load(open(ROOT / "overnight/progress.json"))
    tasks = {t["id"]:t for t in json.load(open(ROOT / "overnight/tasks.json"))}

    lines = [f"# Overnight Report\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
             f"## Summary\n- Attempted: {len(prog['iterations'])}\n- Passed: {prog['summary']['completed']}\n- Failed: {prog['summary']['failed']}\n",
             "## Results\n| ID | Type | Target | Status |\n|---|---|---|---|"]

    for it in prog["iterations"]:
        t = tasks.get(it["task_id"], {})
        st = "✅" if it.get("status") == "passed" else "❌"
        lines.append(f"| {it['task_id']} | {t.get('type','')} | `{t.get('target','')}` | {st} |")

    (ROOT / "overnight/morning_report.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
