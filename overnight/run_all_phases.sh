#!/bin/bash
# Sequential phase execution with logging
cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "=== Starting Multi-Phase Generation at $(date) ==="

for phase_file in overnight/tasks_phase*.json; do
    phase_name=$(basename "$phase_file" .json)
    echo ""
    echo ">>> Processing: $phase_name"
    
    # Update phase6_generate.py to use this task file
    python3 -c "
import json, sys
tasks = json.loads(open('$phase_file').read())
open_tasks = [t for t in tasks if t['status'] == 'open']
print(f'  {len(open_tasks)} tasks to process')
"
    
    # Run generation (modify phase6_generate.py to accept task file path)
    python3 overnight/phase6_generate.py 2>&1 | tee -a "overnight/${phase_name}_log.txt"
    
    echo ">>> Completed: $phase_name"
    sleep 10  # Rate limit between phases
done

echo ""
echo "=== All phases complete at $(date) ==="
python3 -m pytest tests/ -q
