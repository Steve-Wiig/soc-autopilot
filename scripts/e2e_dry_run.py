import sys
import os
import sqlite3
import json
import time
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

DB_PATH = "/tmp/soc_e2e_test.db"
MOCK_PORT = 15432

VALID_LLM_OUTPUT = json.dumps({
    "schema_version": "1.0",
    "classification": "SUSPICIOUS",
    "confidence": 0.85,
    "severity": "MEDIUM",
    "recommended_action": "ENRICH",
    "reasoning_summary": "Observed anomalous PowerShell execution with encoded arguments.",
    "indicators": ["powershell.exe", "-enc"],
    "evidence_refs": ["wazuh:alert:12345"],
    "requires_human_review": True
})

class MockOllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    
    def do_GET(self):
        if self.path == "/v1/models":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "qwen2.5:7b"}]}).encode())

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            response = {"choices": [{"message": {"content": VALID_LLM_OUTPUT}}]}
            self.wfile.write(json.dumps(response).encode())

def setup_db():
    if os.path.exists(DB_PATH): os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    # Added 'severity TEXT' to match the worker's expected schema
    conn.execute("""CREATE TABLE triage_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT, payload_ref TEXT,
        status TEXT, priority INTEGER, created_at TEXT, severity TEXT, attempts INTEGER DEFAULT 0,
        started_at TEXT, lease_expires_at TEXT, last_heartbeat_at TEXT, failure_reason TEXT
    )""")
    conn.execute("""CREATE TABLE verdicts (
        job_id TEXT NOT NULL, result TEXT NOT NULL, processed_at TEXT NOT NULL
    )""")
    
    alert = json.dumps({"event_id": "EVE-999", "rule": {"description": "PowerShell encoded command detected"}})
    conn.execute("""
        INSERT INTO triage_queue (payload, payload_ref, status, priority, severity, created_at, attempts) 
        VALUES (?, ?, 'pending', 5, 'MEDIUM', datetime('now'), 0)
    """, (alert, alert))
    conn.commit()
    return conn

def main():
    print("🚀 Starting E2E Canonical Path Dry Run...\n")
    
    server = HTTPServer(("localhost", MOCK_PORT), MockOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"✅ Mock Local LLM running on http://localhost:{MOCK_PORT}")

    setup_db()
    print("✅ Database initialized with 1 pending job (ID: 1).")

    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath(".")
    env["SOC_MOCK_LLM_URL"] = f"http://localhost:{MOCK_PORT}"

    print("⏳ Running slm_triage_worker.py for 5 seconds...")
    worker_cmd = [sys.executable, "-m", "engine.slm_triage_worker", "--db", DB_PATH, "--lease", "60"]
    process = subprocess.Popen(worker_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    
    time.sleep(5) 
    process.terminate()
    process.wait()

    print("\n🔍 Checking database results...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    queue_status = conn.execute("SELECT status, failure_reason FROM triage_queue WHERE id = 1").fetchone()
    print(f"  Queue Status: {queue_status['status']}")
    if queue_status['failure_reason']:
        print(f"  Failure Reason: {queue_status['failure_reason']}")

    verdict = conn.execute("SELECT result FROM verdicts WHERE job_id = 1").fetchone()
    if verdict:
        result_data = json.loads(verdict['result'])
        print("\n🎉 SUCCESS! The canonical path worked end-to-end:")
        print(f"  ├─ Recommendation ID : {result_data.get('recommendation_id')}")
        print(f"  ├─ Decision ID       : {result_data.get('decision_id')}")
        print(f"  ├─ Policy Outcome    : {result_data.get('outcome')}")
        print(f"  ├─ Model Used        : {result_data['envelope']['model_id']}")
        print(f"  └─ Classification    : {result_data['envelope']['recommendation']['classification']}")
    else:
        print("\n❌ FAILED: No verdict found. The worker may have failed to validate or connect.")
        print("Worker stderr:", process.stderr.read()[-500:])

    server.shutdown()
    if os.path.exists(DB_PATH): os.remove(DB_PATH)
    print("\n🧹 Cleanup complete.")

if __name__ == "__main__":
    main()
