# soc-autopilot Operations Runbook

## Version: 11.9
## Last Updated: 2025-01-15

---

## 1. Starting/Stopping Services

### 1.1 Start All Core Services

```bash
# Activate virtual environment first
source /opt/soc-autopilot/venv/bin/activate

# Start the intake layer (Wazuh + Eve)
cd /opt/soc-autopilot
python -m engine.intake_wazuh --config config/intake_wazuh.yaml --daemon
python -m engine.intake_eve --config config/intake_eve.yaml --daemon

# Start sanitization pipeline
python -m engine.sanitization_pipeline --workers 4 --config config/sanitization.yaml --daemon

# Start queue manager
python -m engine.queue_manager --config config/queue.yaml --daemon

# Start SLM triage workers (adjust count based on GPU/CPU)
python -m engine.slm_triage_worker --workers 8 --model-config config/models.yaml --daemon

# Start enrichment scheduler
python -m engine.enrichment_scheduler --interval 300 --config config/enrichment.yaml --daemon

# Start IOC extractor
python -m engine.ioc_extractor --workers 4 --daemon

# Start hash chain sealer (runs every 60s by default)
python -m engine.hash_chain_sealer --interval 60 --daemon

# Start orchestrator services
python -m orchestrator.context_stitcher --daemon
python -m orchestrator.model_registry --config config/model_registry.yaml --daemon

# Start memory layer
python -m memory.embeddings --daemon
python -m memory.retention --config config/retention.yaml --daemon

# Start quota ledger
python -m engine.quota_ledger --daemon
```

### 1.2 Stop All Services Gracefully

```bash
# Send SIGTERM to all daemon processes using exact module paths
pkill -f "python -m engine.intake_wazuh"
pkill -f "python -m engine.intake_eve"
pkill -f "python -m engine.sanitization_pipeline"
pkill -f "python -m engine.queue_manager"
pkill -f "python -m engine.slm_triage_worker"
pkill -f "python -m engine.enrichment_scheduler"
pkill -f "python -m engine.ioc_extractor"
pkill -f "python -m engine.hash_chain_sealer"
pkill -f "python -m orchestrator.context_stitcher"
pkill -f "python -m orchestrator.model_registry"
pkill -f "python -m memory.embeddings"
pkill -f "python -m memory.retention"
pkill -f "python -m engine.quota_ledger"

# Wait for graceful shutdown (max 30s)
sleep 30

# Force kill if needed (target only our venv python processes)
pkill -9 -f "/opt/soc-autopilot/venv/bin/python"
```

### 1.3 Restart Individual Service

```bash
# Example: Restart SLM triage workers only
pkill -f "python -m engine.slm_triage_worker"
sleep 5
python -m engine.slm_triage_worker --workers 8 --model-config config/models.yaml --daemon

# Verify restart
python -m engine.queue_manager --status
```

### 1.4 Start Overnight Self-Improving Pipeline (v11.11)

```bash
# Schedule via cron (runs 02:00 daily)
# Ensure soc-user has write access to /var/log/soc-autopilot/ and read access to /opt/soc-autopilot/venv/
# Add to /etc/cron.d/soc-autopilot:
# 0 2 * * * soc-user /opt/soc-autopilot/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml >> /var/log/soc-autopilot/self_improver.log 2>&1

# Manual execution for testing (use absolute venv python path)
cd /opt/soc-autopilot
/opt/soc-autopilot/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --dry-run

# Full run with backlog processing (backlog stored in /data/ for consistency with state files)
/opt/soc-autopilot/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --process-backlog /data/self_improver/fix_backlog.json
```

---

## 2. Checking Queue Health

### 2.1 Queue Status Overview

```bash
# Get comprehensive queue status
python -m engine.queue_manager --status --verbose

# Expected output:
# QUEUE STATUS REPORT
# ===================
# intake_raw:        1,234 messages (lag: 12s)
# sanitization:        56 messages (lag: 3s)
# triage_pending:     234 messages (lag: 45s)
# enrichment_pending:  12 messages (lag: 8s)
# writeback_pending:    3 messages (lag: 1s)
# quarantine:          87 messages
# dead_letter:          4 messages
```

### 2.2 Per-Queue Depth and Lag

```bash
# Check specific queue
python -m engine.queue_manager --queue triage_pending --depth --lag

# Check all queues with JSON output for monitoring
python -m engine.queue_manager --status --json | jq '.queues[] | {name: .name, depth: .depth, lag_seconds: .lag_seconds, consumers: .active_consumers}'

# Alert if any queue lag > 300s
python -m engine.queue_manager --status --json | jq -r '.queues[] | select(.lag_seconds > 300) | "ALERT: \(.name) lag=\(.lag_seconds)s"'
```

### 2.3 Consumer Health

```bash
# List active consumers per queue
python -m engine.queue_manager --consumers --verbose

# Check SLM triage worker registration
python -m engine.slm_triage_worker --list-workers

# Expected output:
# WORKER REGISTRY
# ===============
# worker-01: ACTIVE  (pid: 12345, gpu: 0, model: llama-3.1-8b, processed: 1,234)
# worker-02: ACTIVE  (pid: 12346, gpu: 1, model: llama-3.1-8b, processed: 1,198)
# worker-03: STALLED (pid: 12347, gpu: 2, model: llama-3.1-8b, last_heartbeat: 120s ago)
```

### 2.4 Queue Backpressure Metrics

```bash
# Get backpressure indicators
python -m engine.queue_manager --backpressure

# Key metrics to watch:
# - intake_raw growth rate > 100/min = upstream surge
# - triage_pending > 5000 = worker saturation
# - quarantine > 1000 = sanitization/triage failure spike
```

---

## 3. Monitoring Hash Chain Integrity

### 3.1 Verify Current Chain State

```bash
# Check hash chain head and integrity
python -m engine.hash_chain_sealer --verify --full

# Expected output:
# HASH CHAIN VERIFICATION
# =======================
# Chain head:        a3f2e8b1c4d5... (block #1,042,311)
# Last sealed:       2025-01-15 14:23:12 UTC
# Blocks verified:   1,042,311 / 1,042,311 (100%)
# Integrity:         OK
# Orphan blocks:     0
# Gap detected:      NO
```

### 3.2 Verify Specific Range

```bash
# Verify last N blocks
python -m engine.hash_chain_sealer --verify --last 10000

# Verify specific block range
python -m engine.hash_chain_sealer --verify --from-block 1040000 --to-block 1042311
```

### 3.3 Check Sealer Daemon Health

```bash
# Check sealer process
ps aux | grep "python -m engine.hash_chain_sealer"

# Check sealer logs for errors
tail -100 /var/log/soc-autopilot/hash_chain_sealer.log | grep -i error

# Verify sealing interval compliance
python -m engine.hash_chain_sealer --stats --last-hour
# Output shows: seals_per_minute, avg_seal_latency_ms, missed_intervals
```

### 3.4 Repair Broken Chain (Emergency)

```bash
# ONLY RUN IF VERIFICATION FAILS AND YOU HAVE CONFIRMED DATA LOSS
# 1. Stop all writers
pkill -f "python -m engine.queue_manager"
pkill -f "python -m engine.slm_triage_worker"

# 2. Find last good block
python -m engine.hash_chain_sealer --find-last-good --from-block 1040000

# 3. Truncate and reseal (DANGEROUS - requires manual confirmation)
# Note: --truncate-at expects a block NUMBER (integer), not a hash
# WARNING: This creates a gap. The sealer will re-index subsequent blocks on next seal cycle.
python -m engine.hash_chain_sealer --repair --truncate-at 1042000 --confirm-i-understand

# 4. Verify repair succeeded
python -m engine.hash_chain_sealer --verify --full

# 5. Restart services
# (see Section 1.1)
```

### 3.5 Hash Chain Monitoring Alerts

```bash
# Add to monitoring (Prometheus/Grafana)
# Alert if: hash_chain_sealer_missed_intervals > 0
# Alert if: hash_chain_verification_failures > 0
# Alert if: hash_chain_head_age_seconds > 120
```

---

## 4. Handling Quarantine Overflow

### 4.1 Detect Quarantine Growth

```bash
# Check quarantine queue depth
python -m engine.queue_manager --queue quarantine --depth

# Check quarantine growth rate (last hour)
python -m engine.queue_manager --queue quarantine --growth-rate --window 3600

# List quarantine reasons
python -m engine.queue_manager --queue quarantine --sample 100 --show-reason
```

### 4.2 Analyze Quarantine Contents

```bash
# Export quarantine samples for analysis
python -m engine.queue_manager --queue quarantine --export /tmp/quarantine_sample.json --limit 500

# Categorize by rejection reason
python -c "
import json
with open('/tmp/quarantine_sample.json') as f:
    data = json.load(f)
reasons = {}
for msg in data['messages']:
    reason = msg.get('quarantine_reason', 'unknown')
    reasons[reason] = reasons.get(reason, 0) + 1
for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
    print(f'{c:4d}  {r}')
"
```

### 4.3 Remediate Common Quarantine Causes

#### 4.3.1 Sanitization Failures (PII/Secrets)

```bash
# Review sanitization rules
cat config/sanitization.yaml | grep -A5 "patterns:"

# Test specific message against sanitizer
python -m engine.sanitization_pipeline --test-message '{"message": "password=secret123"}'

# Update patterns and reload (no restart needed)
python -m engine.sanitization_pipeline --reload-config
```

#### 4.3.2 Schema Validation Failures

```bash
# Check schema registry
python -m engine.intake_wazuh --show-schemas

# Validate sample against schema
python -m engine.intake_wazuh --validate-sample /tmp/quarantine_sample.json
```

#### 4.3.3 Enrichment Failures

```bash
# Check enrichment scheduler errors
grep -i "enrichment failed" /var/log/soc-autopilot/enrichment_scheduler.log | tail -20

# Re-run enrichment for quarantined messages
python -m engine.enrichment_scheduler --reprocess-quarantine --batch-size 100
```

### 4.4 Emergency Quarantine Drain

```bash
# If quarantine > 5000 and growing: EMERGENCY DRAIN
# 1. Pause intake temporarily
python -m engine.intake_wazuh --pause
python -m engine.intake_eve --pause

# 2. Increase triage workers temporarily
pkill -f "python -m engine.slm_triage_worker"
python -m engine.slm_triage_worker --workers 16 --model-config config/models.yaml --daemon

# 3. Process quarantine with relaxed rules (review first!)
python -m engine.queue_manager --queue quarantine --reprocess --relaxed-sanitization --batch-size 500

# 4. Resume intake
python -m engine.intake_wazuh --resume
python -m engine.intake_eve --resume
```

---

## 5. Recovering from Worker Crashes

### 5.1 Detect Worker Failures

```bash
# Check worker heartbeats
python -m engine.slm_triage_worker --list-workers | grep -E "(STALLED|DEAD|MISSING)"

# Check systemd/journald for OOM kills
journalctl -u soc-autopilot --since "1 hour ago" | grep -i "oom\|killed\|segfault"

# Check GPU memory errors
nvidia-smi -q -d PIDS | grep -A5 "Process ID"
```

### 5.2 Automatic Recovery (Configured)

```bash
# Verify auto-recovery is enabled
grep -A10 "auto_recovery:" config/slm_triage_worker.yaml

# Expected config:
# auto_recovery:
#   enabled: true
#   max_restarts: 3
#   restart_window_seconds: 300
#   health_check_interval: 30
```

### 5.3 Manual Worker Recovery

```bash
# Restart single crashed worker (by GPU ID)
python -m engine.slm_triage_worker --restart-worker --gpu 2 --model-config config/models.yaml

# Restart all workers on specific model
python -m engine.slm_triage_worker --restart-model llama-3.1-8b

# Full worker pool restart
pkill -f "python -m engine.slm_triage_worker"
sleep 10
python -m engine.slm_triage_worker --workers 8 --model-config config/models.yaml --daemon
```

### 5.4 Recover In-Flight Messages

```bash
# Check for messages stuck in triage_pending (worker crashed mid-process)
python -m engine.queue_manager --queue triage_pending --stuck-threshold 300 --list

# Re-queue stuck messages (moves back to triage_pending with retry_count++)
python -m engine.queue_manager --queue triage_pending --requeue-stuck --max-retries 3

# Check dead letter queue
python -m engine.queue_manager --queue dead_letter --depth
python -m engine.queue_manager --queue dead_letter --export /tmp/dlq_export.json --limit 100
```

### 5.5 GPU Recovery

```bash
# Reset GPU if workers show CUDA errors
sudo nvidia-smi -r -i 0  # Reset GPU 0 (requires persistence mode off)

# Better: restart with GPU reset
pkill -f "python -m engine.slm_triage_worker"
sleep 5
sudo nvidia-smi -r -i 0,1,2,3  # Reset all GPUs
sleep 10
python -m engine.slm_triage_worker --workers 8 --model-config config/models.yaml --daemon
```

---

## 6. Rotating API Keys

### 6.1 Rotate OpenRouter API Key (v11.11)

```bash
# 1. Generate new key at https://openrouter.ai/keys
# 2. Update quota ledger (master key store) with new key
python -m engine.quota_ledger --rotate-key openrouter --new-key "sk-or-v1-NEW_KEY_HERE"

# 3. Update llm_client.py config (multi-provider fallback)
# Edit config/llm_providers.yaml:
# openrouter:
#   api_key: "sk-or-v1-NEW_KEY_HERE"
#   priority: 1
#   rate_limit_rpm: 60
#   rate_limit_tpm: 100000

# 4. SECURITY: Restrict permissions on config file
chmod 600 config/llm_providers.yaml

# 5. Reload llm_client without restart (model_registry handles provider reload)
python -m orchestrator.model_registry --reload-providers

# 6. Verify key works (llm_client.py routes internally based on llm_providers.yaml priority; model param is logical name)
python -c "
from orchestrator.llm_client import LLMClient
client = LLMClient.from_config('config/llm_providers.yaml')
try:
    result = client.generate('test', model='claude-3.5-sonnet', max_tokens=5)
    print('Key valid:', result is not None)
except Exception as e:
    print('Key invalid:', str(e))
"
```

### 6.2 Rotate Local Model API Keys (Ollama/vLLM)

```bash
# For vLLM with API key auth
# 1. Generate new key
openssl rand -hex 32

# 2. Update vLLM config
# Edit /etc/vllm/config.yaml:
# api_key: "NEW_KEY_HERE"

# 3. Restart vLLM
sudo systemctl restart vllm

# 4. Update model_registry (which updates llm_providers.yaml internally)
python -m orchestrator.model_registry --update-endpoint vllm-local --api-key "NEW_KEY_HERE"
python -m orchestrator.model_registry --reload-providers

# 5. SECURITY: Restrict permissions
chmod 600 config/llm_providers.yaml
```

### 6.3 Rotate Embedding API Keys

```bash
# For memory.embeddings (if using remote embeddings)
python -m memory.embeddings --rotate-key --provider openai --new-key "sk-NEW_KEY"

# Verify
python -m memory.embeddings --test-connection
```

### 6.4 Update OpenRouter Quota Tracking (v11.11)

```bash
# Check current quota status (openrouter_quota is a helper under engine/ that reads from quota_ledger)
python -m engine.openrouter_quota --status

# Expected output:
# OPENROUTER QUOTA STATUS
# ======================
# Current key:       sk-or-v1-abc... (last 4: def1)
# Daily limit:       1,000,000 tokens
# Used today:        234,567 tokens (23.5%)
# Reset at:          2025-01-16 00:00 UTC
# Rate limit:        60 RPM / 100,000 TPM
# Current usage:     12 RPM / 45,000 TPM

# After key rotation in quota_ledger, reset quota tracking helper
python -m engine.openrouter_quota --reset --key "sk-or-v1-NEW_KEY_HERE"

# Verify fallback chain works (llm_client.py handles fallback internally; test by forcing primary failure)
python -c "
from orchestrator.llm_client import LLMClient
client = LLMClient.from_config('config/llm_providers.yaml')

# Test primary (should succeed with new key)
try:
    r1 = client.generate('test', model='claude-3.5-sonnet', max_tokens=10)
    print('Primary:', 'OK' if r1 else 'FAIL')
except Exception as e:
    print('Primary: FAIL -', str(e))

# Test fallback by temporarily disabling primary in config or using a model only on fallback provider
# The client.generate() returns None on failure (not exception) per implementation
r2 = client.generate('test', model='llama-3.1-405b', max_tokens=10)
print('Fallback:', 'OK' if r2 else 'FAIL')
"
```

### 6.5 Key Rotation Checklist

```bash
# Pre-rotation
[ ] New key generated and stored in password manager
[ ] Old key expiration confirmed
[ ] Rollback plan documented

# Rotation
[ ] Update quota_ledger (master)
[ ] Update llm_providers.yaml
[ ] chmod 600 config/llm_providers.yaml
[ ] Reload model_registry
[ ] Verify all providers respond
[ ] Run test triage on sample alerts

# Post-rotation
[ ] Monitor quota_ledger for 15 min
[ ] Check llm_client fallback logs
[ ] Verify overnight.self_improver uses new key
[ ] Revoke old key at provider
```

---

## 7. Overnight Self-Improving Pipeline Operations (v11.11)

### 7.1 Pipeline Overview

The overnight pipeline (`overnight/self_improver.py`) performs:
- Model performance analysis on previous day's triage decisions
- Automatic prompt optimization for SLM triage worker
- False positive/negative pattern mining
- Backlog processing from `/data/self_improver/fix_backlog.json`
- Multi-provider LLM evaluation via `llm_client.py` with fallback
- Quota-aware execution via `engine.openrouter_quota` (reads from `engine.quota_ledger`)

### 7.2 Manual Pipeline Execution

```bash
# Dry run (no changes applied)
/opt/soc-autopilot/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --dry-run --verbose

# Full run with specific date
/opt/soc-autopilot/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --date 2025-01-14

# Process accumulated backlog (stored in /data/ for consistency)
/opt/soc-autopilot/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --process-backlog /data/self_improver/fix_backlog.json --max-items 500

# Force re-evaluation of specific model
/opt/soc-autopilot/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --reevaluate-model llama-3.1-8b
```

### 7.3 Monitor Pipeline Execution

```bash
# Check last run status
cat /var/log/soc-autopilot/self_improver/latest_run.json | jq .

# Key metrics:
# - "status": "completed" | "partial" | "failed"
# - "models_evaluated": 3
# - "prompts_optimized": 2
# - "backlog_processed": 47
# - "quota_consumed": {"openrouter": 125000, "local": 0}
# - "fallback_activations": 3
# - "duration_seconds": 1847
```

### 7.4 Handle Pipeline Failures

```bash
# Check failure reason
cat /var/log/soc-autopilot/self_improver/latest_run.json | jq '.error'

# Common failures and fixes:

# 1. Quota exhausted
# Check: python -m engine.openrouter_quota --status
# Fix: Wait for reset or rotate key (Section 6.1)

# 2. All LLM providers failed
# Check: grep "fallback exhausted" /var/log/soc-autopilot/self_improver.log
# Fix: Verify llm_providers.yaml, check network connectivity

# 3. Backlog corruption
# Check: python -m overnight.self_improver --validate-backlog /data/self_improver/fix_backlog.json
# Fix: python -m overnight.self_improver --repair-backlog /data/self_improver/fix_backlog.json

# 4. Prompt optimization failed validation
# Check: grep "validation failed" /var/log/soc-autopilot/self_improver.log
# Fix: Review proposed prompts in /tmp/self_improver_proposals/
```

### 7.5 Apply/Revert Pipeline Changes

```bash
# Review proposed changes before applying
ls -la /tmp/self_improver_proposals/
cat /tmp/self_improver_proposals/prompt_changes.yaml

# Apply approved changes
python -m overnight.self_improver --apply-proposals /tmp/self_improver_proposals/ --confirm

# Revert last applied changes
python -m overnight.self_improver --revert-last --confirm

# View change history
python -m overnight.self_improver --history --limit 10
```

---

## 8. Emergency Procedures

### 8.1 Full System Reset

```bash
# 1. Stop all services (Section 1.2)
# 2. Clear queues (CAUTION: DATA LOSS)
python -m engine.queue_manager --purge-all --confirm-i-understand

# 3. Reset hash chain (CAUTION: BREAKS AUDIT TRAIL)
python -m engine.hash_chain_sealer --reset --confirm-i-understand

# 4. Clear quarantine and dead letter
python -m engine.queue_manager --queue quarantine --purge --confirm
python -m engine.queue_manager --queue dead_letter --purge --confirm

# 5. Restart all services (Section 1.1)
```

### 8.2 Disaster Recovery Checklist

```bash
# Run after any major incident
[ ] Verify hash chain integrity (Section 3.1)
[ ] Check queue depths normal (Section 2.1)
[ ] Verify all workers healthy (Section 2.3)
[ ] Test end-to-end flow with sample alert
[ ] Confirm quota ledger operational
[ ] Verify overnight pipeline can run
[ ] Check monitoring alerts clear
[ ] Document incident in runbook
```

---

## 9. Key File Paths Reference

| Component | Config Path | Log Path | Data Path |
|-----------|-------------|----------|-----------|
| Intake Wazuh | `config/intake_wazuh.yaml` | `/var/log/soc-autopilot/intake_wazuh.log` | `/data/queue/intake_raw` |
| Intake Eve | `config/intake_eve.yaml` | `/var/log/soc-autopilot/intake_eve.log` | `/data/queue/intake_raw` |
| Sanitization | `config/sanitization.yaml` | `/var/log/soc-autopilot/sanitization.log` | `/data/queue/sanitization` |
| Queue Manager | `config/queue.yaml` | `/var/log/soc-autopilot/queue_manager.log` | `/data/queue/*` |
| SLM Triage | `config/slm_triage_worker.yaml` | `/var/log/soc-autopilot/slm_triage.log` | `/data/queue/triage_pending` |
| Enrichment | `config/enrichment.yaml` | `/var/log/soc-autopilot/enrichment.log` | `/data/queue/enrichment_pending` |
| Hash Chain | `config/hash_chain.yaml` | `/var/log/soc-autopilot/hash_chain_sealer.log` | `/data/hash_chain/` |
| Model Registry | `config/model_registry.yaml` | `/var/log/soc-autopilot/model_registry.log` | `/data/models/` |
| LLM Providers | `config/llm_providers.yaml` | `/var/log/soc-autopilot/llm_client.log` | - |
| Self Improver | `config/self_improver.yaml` | `/var/log/soc-autopilot/self_improver.log` | `/data/self_improver/` |
| OpenRouter Quota | `config/openrouter_quota.yaml` | `/var/log/soc-autopilot/openrouter_quota.log` | `/data/quota/openrouter.json` |
| Fix Backlog | - | - | `/data/self_improver/fix_backlog.json` |
| Retention | `config/retention.yaml` | `/var/log/soc-autopilot/retention.log` | `/data/memory/` |
| Embeddings | `config/embeddings.yaml` | `/var/log/soc-autopilot/embeddings.log` | `/data/embeddings/` |

---

## 10. Useful One-Liners

```bash
# Quick health check
python -m engine.queue_manager --status --json | jq -r '.overall_health'

# Tail all logs
tail -f /var/log/soc-autopilot/*.log

# Count messages processed last hour
grep "processed" /var/log/soc-autopilot/slm_triage.log | grep "$(date -d '1 hour ago' '+%H:')" | wc -l

# Check GPU utilization
watch -n 5 nvidia-smi

# Check disk space for queues
df -h /data/queue

# Verify all daemons running
pgrep -af "python -m engine\.|python -m orchestrator\.|python -m memory\." | wc -l
```

---

*End of Runbook*# Operator Playbook — Lessons from the Overnight Pipeline

**v1.0 — 2026-08-26** — Operational wisdom for future LLM sessions and human operators.

---

## 1. The Overnight Drain

overnight_run.sh is a closed-loop autonomous agent: reads fix_backlog.json,
generates fixes via Gemini/OpenRouter/Groq, test-gates every fix, commits the good
ones, defers failures after 3 attempts, writes overnight/morning_report.md.

Monitor:

    bash overnight/dashboard.sh
    tail -f overnight/run_*.log

Normal behavior:
- Backlog drops in steps (at pass boundaries, not per-commit)
- ~1-3 commits/min during active work
- Every rejected fix is a safety gate working — not a failure
- Deferred queue grows as hard items get quarantined

Intervene only if: process dies, budget gate trips, or the test suite breaks.
Otherwise let it run — AST parsing, pytest rollback, and truncation guards prevent corruption.

---

## 2. Manual Triage of Deferred Items

Deferred items (overnight/fix_backlog_deferred.json) failed 3x and need human judgment.
Classify each as one of:

- PHANTOM — the drain already fixed it; the entry is stale. Clear it, no code change.
- REJECT — the advisory is wrong. Clear it with a rationale.
- FIX — a real issue. Apply it surgically, test-first.

---

## 3. The Five Iron Rules (learned the hard way)

### Rule 1 — Surgical, never bulk
Bulk string-replacement across multiple files BREAKS interdependent code
(signature + body + callers + tests) in ways py_compile cannot catch.
Fix ONE item at a time. This cost us a full revert once. Do not repeat it.

### Rule 2 — Avoid files the drain is actively committing

    git log --since='20 minutes ago' --name-only --pretty=format: | grep -v '^$' | sort -u

Do not edit those files — you will race the drain and cause conflicts.

### Rule 3 — Test-first, always
Before committing any manual fix:

    python3 -m py_compile <file>.py
    python3 -m pytest tests/test_<file>*.py -q
    python3 -m pytest tests/ -q

If anything fails, do not commit. The drain's pytest gate would reject it; so should you.

### Rule 4 — Verify the issue still exists (phantom check)
Before fixing, check whether the drain already resolved it:

    git log --oneline -- <file> | head -5

Recent Auto-fix commits on the file often mean the item is a phantom.

### Rule 5 — Guess nothing about tests
Never assume test filenames or expected behavior. Read the actual test file first.
Guessing test names gave us zero verification once. Always confirm.

---

## 4. Known Rejection Patterns

- "Combine two UPDATEs into one CASE" — Loop required for approval gates. REJECT.
- "Add audit logging to CI validation gate" — Stateless validator, not a handoff path. REJECT.
- "sys.exit() in __main__ violates AMEND-64" — AMEND-64 targets library functions, not CLI entry points. REJECT.
- "Move inline comments to docstring" — Cosmetic churn, no functional value. REJECT.

---

## 5. The Meta-Lesson

The LLMs are the tradespeople — they swing the hammer. You are the General Contractor:
you read the blueprints, inspect the foundation, and reject substandard work.

Your value is not memorizing syntax. It is:
- Designing secure, resilient, fault-tolerant architectures
- Treating the AI as an untrusted execution environment (safety gates)
- Budget and resource control
- Audit trails and compliance

The code the AI writes is the output. The architecture and safety discipline are yours.

---

## 6. Pre-Commit Checklist (manual fixes)

- File NOT in the drain's active-commit list (last 20 min)
- Issue verified to still exist (phantom check done)
- Fix is surgical — one file, one issue
- py_compile passes
- Affected tests pass
- Full suite passes
- Deferred entry cleared
- Commit message explains what + why

---

## 7. Morning Routine

1. cat overnight/morning_report.md
2. bash overnight/dashboard.sh
3. python3 -m pytest tests/ -q  (confirm green)
4. git log --oneline --since='12 hours ago'
5. Triage new deferred items per Section 2

---
v1.0 — soc-autopilot overnight pipeline operator lessons

---

## 8. Session Addenda — Additional Failure Modes (discovered while operating the drain)

### 8.1 Duplicate advisories in the backlog
The backlog can contain TWIN copies of the same advisory. Clearing by list index
removes one copy and leaves the twin, which the drain keeps retrying (burning quota).
Always clear by description-substring match, never by index.

### 8.2 Queue-file race condition
The drain holds the backlog in memory and rewrites the JSON after each item. Editing
fix_backlog.json or fix_backlog_deferred.json while the drain runs gets OVERWRITTEN on
its next save. Queue surgery requires: stop drain -> edit -> commit -> relaunch.

### 8.3 The config-class trap (does NOT fix module-level side effects)
Wrapping os.environ.get() in a class with class attributes still evaluates the calls at
class-definition time, which is still module load. To make env reads truly lazy, use a
cached function:

    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _config():
        return {"archive_base": os.environ.get("ARCHIVE_BASE", "/archive/iocs")}

### 8.4 Global identifier replacement corrupts definitions
str.replace("ARCHIVE_BASE", "Cfg.ARCHIVE_BASE") rewrites the symbol inside its OWN
definition and inside docstrings, producing a NameError on import. NEVER globally replace
a bare identifier. Anchor replacements on full, unique lines or statements.

### 8.5 Reuse proven entry points, don't reinvent
A custom wrapper that hand-rolled budget/key init crashed silently where the battle-tested
--drain-backlog CLI worked. Prefer the CLI paths that already ran successfully overnight.

### 8.6 Silent background crashes
An empty log usually means the job crashed during startup AND stdout was buffered. Launch
with PYTHONUNBUFFERED=1, then sleep a few seconds and tail to confirm it entered its main
loop before walking away.

### 8.7 .env is not the shell environment
nohup subshells do not inherit .env automatically. Run 'set -a; source .env; set +a' in the
SAME shell before launching, or API keys arrive empty and every call returns 401.

---
*Addenda captured 2026-08-27 during hard-items triage session*

### 8.8 Module-level __getattr__ does NOT work for internal references
Defining __getattr__ in a module only intercepts EXTERNAL attribute access
(e.g. `from module import X` or `module.X`). Bare-name references INSIDE the
module's own functions (e.g. `if shutil.which(ZSTD_COMMAND)`) bypass __getattr__
and raise NameError. To lazily provide module globals that internal code AND
monkeypatch-based tests both use, prefer plain module-level names plus an
explicit _load_config() called from entry points — not __getattr__.

### 8.9 Heredocs with nested triple-quotes are brittle
A Python patch script inside a bash heredoc that contains triple-quoted strings
with its own triple-quoted strings will silently mis-parse. Always write the
patch to a temp file first (`cat > /tmp/patch.py << 'EOF'`) then execute it.

---

## 9. The Prompt Feedback Loop (lessons_learned.json)

### 9.1 Why it exists
By default the drain was STATELESS: every fix attempt used the same base prompt,
so the LLMs kept rediscovering the same traps (retention.py failed 5x on the same
monkeypatch issue). The playbook captured wisdom for humans but not for the models.

### 9.2 How it works
overnight/lessons_learned.json maps file-name substrings (plus a special "_global"
key) to constraint strings. self_improver._lessons_block_for(file_path) matches the
current file and injects a "KNOWN CONSTRAINTS" block into the fix prompt, so each
attempt carries the accumulated architectural wisdom.

### 9.3 Maintaining it
After any manual architect fix or a repeatedly-deferred item, distill the lesson into
a one-line imperative constraint and add it under the matching file key (or "_global"
if universal). Example: "do NOT remove DB_PATH; tests patch engine.quota_ledger.DB_PATH."

### 8.10 Stateless retry is the biggest hidden cost
Retrying a deferred item without new context just re-fails the same way. Always add
the discovered constraint to lessons_learned.json BEFORE re-queuing a deferred item.

## 🛡️ CRITICAL OPERATIONAL LESSONS (Hard-Won from Production)

*Added: 2026-08-29*

These are non-negotiable rules discovered during actual autonomous operation. Ignoring them leads to quota burn, corrupted state, or silent failures.

### 1. The Queue-File Race Condition
**Symptom:** The background drain loop overwrites manual edits made to `fix_backlog.json`.
**Resolution:** **NEVER** edit the backlog while the drain is running. 
**Workflow:** 
1. Run `lock_backlog` (creates `overnight/backlog.lock`)
2. The drain will now gracefully skip processing and print a warning.
3. Edit and `git commit` your changes to the JSON.
4. Run `unlock_backlog` to resume autonomous processing.

### 2. The Configuration-Class Trap
**Symptom:** Moving environment variable access into class attributes does *not* make it lazy. Class attributes are evaluated at definition/import time, meaning `.env` files loaded *after* import will be ignored.
**Resolution:** Always read environment variables inside functions/methods at runtime, or use `os.getenv` with explicit reload logic if dynamic changes are expected.

### 3. Global Replacement Corruption
**Symptom:** Blind `str.replace()` on identifiers (e.g., replacing `user` with `admin_user`) can corrupt unrelated definitions, docstrings, or comments.
**Resolution:** Use anchored, unique replacements (e.g., regex with word boundaries `\buser\b`) or AST-based refactoring for code modifications.

### 4. Duplicate Advisories Burn Quota
**Symptom:** Twin advisories in the queue cause the drain to repeatedly retry the same unfixable issue, burning API quota.
**Resolution:** Clear duplicates by matching `description`/`content`, **never** by list index (which shifts as items are removed).

### 5. `.env` Inheritance in Subprocesses
**Symptom:** A `nohup python3 ...` subprocess does not automatically inherit variables from a `.env` file unless explicitly told to.
**Resolution:** The launch script must explicitly source the environment (e.g., `set -a; source .env; set +a`) before invoking the Python process.

### 6. Silent Background Crashes
**Symptom:** A background process appears to be running (PID exists) but has silently exited its main loop due to an unhandled exception.
**Resolution:** Always use unbuffered output (`python3 -u`) and verify the process is actively logging or check its state via a dashboard command, not just `pgrep`.

### 7. Reuse Proven Entry Points
**Symptom:** Writing custom wrapper scripts that reproduce initialization logic often misses edge cases handled by the main CLI.
**Resolution:** Prefer the tested `--drain-backlog` CLI entry point over custom ad-hoc wrappers.
# soc-autopilot Operator Manual v11.11

## ⚠️ Breaking Changes (v11.11)

- **Removed**: `engine/intake_syslog.py` — Migrate to `intake_wazuh.py` or `intake_eve.py` immediately.
- **Schema Change**: `sanitization_pipeline.py` now requires `config/sanitization_rules.yaml` v2 schema (adds `pii_entity_types` field).
- **Hash Chain**: Seal interval reduced from 10k to 1k events for higher audit granularity.
- **New Dependency**: `liburing-dev` must be installed **before** building the Python environment (`apt install liburing-dev` then `pip install -r requirements.txt`).

---

## 1. System Overview

soc-autopilot is a local Security Operations Center automation platform designed for air-gapped and hybrid environments. The platform processes security events through a multi-layered pipeline:

**Engine Layer** (`engine/`):
- `intake_wazuh.py` — Wazuh agent log ingestion via JSON socket
- `intake_eve.py` — Suricata EVE JSON ingestion
- `sanitization_pipeline.py` — PII redaction, field normalization, schema validation
- `queue_manager.py` — Priority queue with Redis backend, TTL-based eviction
- `slm_triage_worker.py` — Local SLM inference for alert triage (confidence scoring, MITRE ATT&CK tagging)
- `enrichment_scheduler.py` — Async IOC enrichment (VirusTotal, AbuseIPDB, OTX)
- `ioc_extractor.py` — Regex + ML-based indicator extraction
- `hash_chain_sealer.py` — Append-only hash chain for audit integrity
- `quota_ledger.py` — Token budget tracking per model/provider

**Orchestrator Layer** (`orchestrator/`):
- `model_registry.py` — Model metadata, capability tags, routing rules
- `context_stitcher.py` — RAG context assembly from memory layer

**Memory Layer** (`memory/`):
- `retention.py` — TTL-based purge, legal hold, GDPR compliance
- `embeddings.py` — Local embedding generation (sentence-transformers), vector index management

**Overnight Self-Improving Pipeline** (`overnight/`):
- `self_improver.py` — Nightly model fine-tuning loop using triage feedback
- `llm_client.py` — Multi-provider fallback (Ollama, vLLM, OpenRouter) with rate-limit management
- `openrouter_quota.py` — OpenRouter credit tracking, daily budget enforcement
- `fix_backlog.json` — Persistent queue of failed self-improvement tasks for retry (stored in `/var/lib/soc/fix_backlog.json`)

---

## 2. Hardware Requirements (Section 28)

| Component | Minimum | Recommended | Notes |
|-----------|---------|-------------|-------|
| CPU | 8 cores (AVX2) | 16+ cores (AVX-512) | SLM inference benefits from AVX-512 VNNI |
| RAM | 32 GB DDR4 | 64 GB DDR5 | Embeddings index + model weights + Redis |
| GPU | NVIDIA RTX 3080 (10 GB) | 2× RTX 4090 (24 GB) | vLLM tensor parallelism; CUDA 12.1+ |
| Storage | 500 GB NVMe | 2 TB NVMe RAID-1 | WAL + vector index + model checkpoints |
| Network | 1 Gbps | 10 Gbps | Intra-cluster replication, intake throughput |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS | Kernel 6.8+ for io_uring support |

**Section 28 Compliance**: All production deployments must pass `scripts/validate_hardware.py --section-28` (exit code 0 = pass, 1 = fail, 2 = warning). Run weekly via cron.

**Critical Note for Ubuntu 24.04**: Install `liburing-dev` **before** creating the Python virtual environment:
```bash
apt update && apt install -y liburing-dev
python3 -m venv /opt/soc/venv
/opt/soc/venv/bin/pip install -r requirements.txt
```
Without `liburing-dev` present at build time, `intake_wazuh.py` falls back to epoll with ~15% throughput reduction.

---

## 3. Database Setup

### 3.1 PostgreSQL (Primary Metadata Store)

```bash
# Initialize schema
psql -U soc_admin -d local_soc -f sql/schema_v11.sql

# Verify migrations
alembic -c alembic.ini upgrade head
# Expected exit codes: 0=success, 1=partial, 2=conflict, 3=db_locked
```

**Required extensions**: `pgvector`, `uuid-ossp`, `pg_trgm`, `btree_gin`

### 3.2 Redis (Queue + Cache)

```bash
# Configure persistence
redis-cli CONFIG SET appendonly yes
redis-cli CONFIG SET appendfsync everysec
redis-cli CONFIG SET maxmemory 8gb
# WARNING: Do NOT use 'allkeys-lru' — it evicts queue keys causing data loss.
# Use 'volatile-lru' and ensure queue keys have no TTL (PERSIST) or very long TTL.
redis-cli CONFIG SET maxmemory-policy volatile-lru
```

**Queue Key Protection**: After starting intake adapters, verify queue keys are persistent:
```bash
redis-cli -n 1 PERSIST triage:queue:high triage:queue:normal triage:queue:low
```

### 3.3 Vector Index (FAISS on Disk)

```bash
# Initialize empty index
python -m memory.embeddings init-index --dim 1024 --index-type IVF4096,PQ32
# Exit codes: 0=created, 1=exists, 2=permission_denied, 3=disk_full
```

---

## 4. Running Intake Adapters

### 4.1 Wazuh Intake (`engine/intake_wazuh.py`)

```bash
# Foreground (debug)
python -m engine.intake_wazuh --config config/intake_wazuh.yaml --log-level DEBUG

# Systemd service (production)
systemctl start soc-intake-wazuh
systemctl status soc-intake-wazuh
# Exit codes: 0=running, 1=config_error, 2=socket_bind_fail, 3=redis_unavailable
```

**Config** (`config/intake_wazuh.yaml`):
```yaml
listen: "0.0.0.0:6060"
batch_size: 500
flush_interval_ms: 100
redis_url: "redis://localhost:6379/1"
sanitization_rules: "config/sanitization_rules.yaml"
```

**SECURITY WARNING**: Port 6060 binds to `0.0.0.0` by default and lacks native TLS/Auth. **Firewall this port to only accept traffic from the Wazuh manager IP(s)**:
```bash
ufw allow from <WAZUH_MANAGER_IP> to any port 6060 proto tcp
```

### 4.2 Suricata EVE Intake (`engine/intake_eve.py`)

```bash
python -m engine.intake_eve --tail /var/log/suricata/eve.json --redis-url redis://localhost:6379/1
# Exit codes: 0=ok, 1=file_not_found, 2=json_parse_error, 3=queue_full
```

### 4.3 Health Check

```bash
curl -s http://localhost:8081/health/intake | jq '.adapters[] | {name, status, lag_ms}'
# Expected: all adapters "healthy", lag_ms < 500
```

---

## 5. Monitoring the Triage Queue

### 5.1 Queue Dashboard

```bash
# Real-time queue depth (adjust -n <db_index> if Redis DB customized)
watch -n 2 'redis-cli -n 1 LLEN triage:queue:high && redis-cli -n 1 LLEN triage:queue:normal && redis-cli -n 1 LLEN triage:queue:low'

# Worker status
python -m engine.queue_manager status --format json
# Output: {"workers": 4, "idle": 1, "processing": 3, "backlog": 127, "avg_latency_ms": 245}
```

### 5.2 SLM Triage Worker (`engine/slm_triage_worker.py`)

```bash
# Start workers (systemd)
systemctl start soc-triage-worker@1 soc-triage-worker@2 soc-triage-worker@3 soc-triage-worker@4

# Manual run with profiling
python -m engine.slm_triage_worker --worker-id 1 --model mistral-7b-instruct-v0.3 --profile
# Exit codes: 0=shutdown, 1=model_load_fail, 2=queue_disconnect, 3=oom, 4=quota_exhausted
```

### 5.3 Key Metrics (Prometheus + Grafana)

| Metric | Alert Threshold | Dashboard Panel |
|--------|-----------------|-----------------|
| `soc_triage_queue_depth` | > 1000 for 5m | Queue Backlog |
| `soc_triage_latency_p99` | > 30s | Latency Heatmap |
| `soc_triage_confidence_low` | > 20% of alerts | Confidence Distribution |
| `soc_worker_oom_total` | > 0 | Worker Health |

---

## 6. Running Retention Cron

### 6.1 Daily Retention Job (`memory/retention.py`)

```bash
# Cron entry (02:30 UTC daily)
30 2 * * * /opt/soc/venv/bin/python -m memory.retention run --config config/retention.yaml >> /var/log/soc/retention.log 2>&1

# Manual execution with dry-run
python -m memory.retention run --dry-run --verbose
# Exit codes: 0=success, 1=config_error, 2=db_lock, 3=legal_hold_conflict, 4=partial_failure
```

### 6.2 Retention Policy (`config/retention.yaml`)

```yaml
policies:
  - name: "raw_events"
    table: "events_raw"
    ttl_days: 30
    legal_hold_tag: "litigation_hold"
  - name: "enriched_events"
    table: "events_enriched"
    ttl_days: 365
  - name: "embeddings"
    index: "faiss_main"
    ttl_days: 730
    purge_orphaned_vectors: true
  - name: "triage_feedback"
    table: "triage_feedback"
    ttl_days: 1095  # 3 years for model training
```

### 6.3 Verification

```bash
python -m memory.retention verify --policy raw_events
# Output: {"scanned": 2847321, "purged": 12453, "errors": 0, "duration_ms": 45210}
```

---

## 7. Checking Hash-Chain Integrity

### 7.1 Seal Verification (`engine/hash_chain_sealer.py`)

```bash
# Full chain verification (run weekly)
python -m engine.hash_chain_sealer verify --full --config config/hash_chain.yaml
# Exit codes: 0=valid, 1=corrupt, 2=missing_seal, 3=config_error, 4=truncated

# Incremental verification (daily cron)
python -m engine.hash_chain_sealer verify --since-last-seal
```

### 7.2 Seal Generation (Automatic)

The sealer runs as a background thread in `queue_manager.py` every 1000 events or 1 hour (whichever comes first). Manual seal:

```bash
python -m engine.hash_chain_sealer seal --force
# Exit codes: 0=sealed, 1=queue_empty, 2=redis_fail, 3=write_fail
```

### 7.3 Audit Log

```bash
# View last 10 seals
sqlite3 /var/lib/soc/hash_chain.db "SELECT seal_id, timestamp, event_count, root_hash FROM seals ORDER BY seal_id DESC LIMIT 10;"
```

---

## 8. Overnight Self-Improving Pipeline (v11.11)

### 8.1 Pipeline Overview

The overnight pipeline runs 03:00-05:00 local time, consuming triage feedback to improve the local SLM:

1. **Data Collection** — Pulls `triage_feedback` where `used_for_training=false`
2. **Dataset Construction** — Formats as instruction-tuning pairs (prompt: alert context, completion: analyst decision)
3. **Training Loop** — LoRA fine-tuning on base model (default: `mistral-7b-instruct-v0.3`)
4. **Evaluation** — Benchmarks against held-out set (F1, calibration error)
5. **Promotion** — If metrics improve, registers new adapter in `model_registry.py`
6. **Cleanup** — Marks feedback rows `used_for_training=true`

### 8.2 Running the Pipeline (`overnight/self_improver.py`)

```bash
# Systemd timer (recommended)
systemctl enable --now soc-self-improver.timer

# Manual execution (ALWAYS run from /opt/soc/ project root)
cd /opt/soc && python -m overnight.self_improver run --config config/self_improver.yaml --verbose
# Exit codes:
#   0 = success, model promoted
#   1 = config error
#   2 = insufficient feedback data (< 100 samples)
#   3 = training failed (OOM, divergence)
#   4 = evaluation failed (metrics regressed)
#   5 = promotion blocked (quota, registry lock)
#   6 = fix_backlog processing required (pipeline halts if backlog has unrecoverable tasks)
```

**Systemd Unit Requirement**: The `soc-self-improver.service` must include:
```ini
Restart=on-failure
RestartPreventExitStatus=6
```
This ensures exit code 6 (fix_backlog intervention required) forces manual operator action.

### 8.3 Configuration (`config/self_improver.yaml`)

```yaml
schedule: "0 3 * * *"  # 03:00 daily
base_model: "mistral-7b-instruct-v0.3"
lora_config:
  r: 16
  alpha: 32
  dropout: 0.05
  target_modules: ["q_proj", "v_proj", "k_proj", "o_proj"]
training:
  epochs: 3
  batch_size: 4
  grad_accum: 8
  lr: 2e-4
  max_seq_len: 4096
evaluation:
  min_f1_improvement: 0.02
  max_calibration_error: 0.15
  holdout_fraction: 0.1
providers:
  primary: "vllm"
  fallback: ["ollama", "openrouter"]
quota:
  daily_token_budget: 500000
  openrouter_daily_usd: 10.00
```

### 8.4 Multi-Provider LLM Client (`overnight/llm_client.py`)

**Important**: Always run from the project root (`/opt/soc/`) or ensure `PYTHONPATH` includes `/opt/soc/` in your shell profile (`export PYTHONPATH=/opt/soc:$PYTHONPATH`).

```python
from overnight.llm_client import MultiProviderClient, ProviderConfig

client = MultiProviderClient([
    ProviderConfig(name="vllm", base_url="http://localhost:8000/v1", priority=1, rate_limit_rpm=600),
    ProviderConfig(name="ollama", base_url="http://localhost:11434/v1", priority=2, rate_limit_rpm=100),
    ProviderConfig(name="openrouter", base_url="https://openrouter.ai/api/v1", priority=3, rate_limit_rpm=50, api_key_env="OPENROUTER_API_KEY"),
])

# Automatic fallback on 429, 503, timeout
response = client.chat.completions.create(
    model="mistral-7b-instruct-v0.3",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.1,
    max_tokens=2048,
)
```

**Rate-limit management**: Token bucket per provider, shared across workers via Redis (`quota:llm:{provider}`). Exhaustion triggers fallback.

**Air-Gapped Environments**: If deployed without internet, the `openrouter` provider will fail with connection errors. Verify connectivity:
```bash
curl -I https://openrouter.ai/api/v1/models --max-time 5
# If this fails, remove 'openrouter' from the fallback list in config/self_improver.yaml
```

### 8.5 OpenRouter Quota Tracking (`overnight/openrouter_quota.py`)

The `openrouter_daily_usd` limit is a **soft limit with warning only**. The script logs a `WARNING` when 80% is reached and `CRITICAL` at 100%, but **does not automatically stop the pipeline**.

**Critical Behavior**: If `openrouter_daily_usd` is reached, the `llm_client` will automatically shift to the next available provider in the `fallback` list. **If no local providers (vLLM, Ollama) are configured and healthy, the pipeline will stall.**

```bash
# Check current usage
python -m overnight.openrouter_quota status
# Output: {"daily_used_usd": 3.42, "daily_limit_usd": 10.00, "remaining_usd": 6.58, "reset_utc": "2025-01-15T00:00:00Z"}

# Reset (manual override)
python -m overnight.openrouter_quota reset --confirm
# Exit codes: 0=ok, 1=not_authorized, 2=api_error
```

### 8.6 Fix Backlog (`/var/lib/soc/fix_backlog.json`)

**Location**: `/var/lib/soc/fix_backlog.json` (persistent data directory, NOT in source tree). The `self_improver.py` module **explicitly uses this absolute path**; ensure the service user has write permissions to `/var/lib/soc/`. Do not rely on relative paths.

Failed self-improvement tasks are persisted here for manual review:

```json
{
  "tasks": [
    {
      "task_id": "simp_20250114_030000_abc123",
      "stage": "training",
      "error": "CUDA OOM: tried to allocate 2.50 GiB",
      "timestamp": "2025-01-14T03:15:22Z",
      "retry_count": 2,
      "max_retries": 3,
      "context": {"batch_size": 4, "grad_accum": 8, "seq_len": 4096}
    }
  ]
}
```

**Recovery**:
```bash
# Inspect backlog
python -m overnight.self_improver backlog list

# Retry specific task
python -m overnight.self_improver backlog retry --task-id simp_20250114_030000_abc123 --reduce-batch-size

# Clear resolved
python -m overnight.self_improver backlog clear --older-than 7d
```

### 8.7 Quota Ledger Billing Export

Generate monthly billing report for token usage across all providers:

```bash
# Monthly billing export (run 1st of month)
python -m engine.quota_ledger export_billing --month 2025-01 --output /var/log/soc/billing_2025-01.json
# Exit codes: 0=success, 1=db_error, 2=permission_denied

# Output format:
# {"period": "2025-01", "providers": {"vllm": {"tokens": 12450000, "est_cost_usd": 0.0}, "openrouter": {"tokens": 892000, "est_cost_usd": 4.46}}, "total_est_cost_usd": 4.46}
```

Add to monthly checklist (Section 10.3).

---

## 9. Troubleshooting Common Failures

### 9.1 Intake Adapter Failures

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `intake_wazuh` exit 2 | Port 6060 in use | `ss -ltnp | grep 6060`, kill conflicting process |
| `intake_eve` exit 2 | Malformed JSON line | `jq -c . /var/log/suricata/eve.json | tail -n 1000 > /tmp/test.json && python -m engine.intake_eve --tail /tmp/test.json` (use `tail` to catch end-of-file corruption) |
| Redis `OOM` | Queue backlog > 10k | Scale workers: `systemctl start soc-triage-worker@5` |

### 9.2 Triage Worker Failures

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| 1 | Model load fail | Check `/var/log/soc/triage-worker*.log` for `torch.cuda.OutOfMemoryError`; reduce `batch_size` in config |
| 3 | OOM during inference | Enable `offload_to_cpu` in `model_registry.py` for this model |
| 4 | Quota exhausted | Check `quota_ledger.py` dashboard; wait for reset or increase budget |

### 9.3 Retention Job Failures

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| 2 | DB lock | `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state='idle in transaction' AND query LIKE '%retention%';` |
| 3 | Legal hold conflict | Review `legal_hold` table; coordinate with legal before forcing purge |

### 9.4 Hash Chain Corruption

```bash
# Diagnose
python -m engine.hash_chain_sealer verify --full --verbose 2>&1 | tail -50

# Rebuild from last good seal (DANGEROUS - requires audit approval)
python -m engine.hash_chain_sealer rebuild --from-seal 12450 --confirm-i-understand
```

### 9.5 Self-Improver Pipeline Failures

| Exit Code | Stage | Resolution |
|-----------|-------|------------|
| 2 | Data collection | Wait for more feedback; minimum 100 samples required |
| 3 | Training | Reduce `batch_size` to 2, `grad_accum` to 16; check GPU memory |
| 4 | Evaluation | New model regressed; check `fix_backlog.json` for details |
| 5 | Promotion | Registry lock; `python -m orchestrator.model_registry unlock --force` |
| 6 | Fix backlog | Run `python -m overnight.self_improver backlog list` and address manually |

### 9.6 OpenRouter Quota Exhausted

```bash
# Check quota
python -m overnight.openrouter_quota status

# Switch to local-only mode (edit config)
sed -i 's/providers:.*/providers:\n  primary: "vllm"\n  fallback: ["ollama"]/' config/self_improver.yaml

# Restart pipeline
systemctl restart soc-self-improver
```

### 9.7 Network / Firewall (Air-Gapped Deployments)

If the environment is air-gapped, the `openrouter` provider in `llm_client.py` will fail with connection errors. Verify and adjust:

```bash
# Test connectivity
curl -I https://openrouter.ai/api/v1/models --max-time 5

# If failed, remove openrouter from fallback chain
sed -i '/openrouter/d' config/self_improver.yaml
# Ensure local providers are configured:
# providers:
#   primary: "vllm"
#   fallback: ["ollama"]
systemctl restart soc-self-improver
```

---

## 10. Operational Checklists

### 10.1 Daily (Automated via Cron)

- [ ] Retention job completes (exit 0)
- [ ] Hash chain incremental verify (exit 0)
- [ ] Self-improver pipeline runs (exit 0 or 2)
- [ ] Queue depth < 500
- [ ] All workers healthy (`soc_triage_worker_oom_total == 0`)

### 10.2 Weekly

- [ ] Full hash chain verification
- [ ] Hardware validation (`scripts/validate_hardware.py --section-28`)
- [ ] Model registry audit (`python -m orchestrator.model_registry audit`)
- [ ] OpenRouter quota review
- [ ] Fix backlog review (`python -m overnight.self_improver backlog list`)

### 10.3 Monthly

- [ ] Embedding index rebuild (`python -m memory.embeddings rebuild --full`)
- [ ] Disaster recovery test (restore from backup, verify hash chain)
- [ ] Capacity planning (storage growth, GPU utilization trends)
- [ ] **Billing export**: `python -m engine.quota_ledger export_billing --month $(date -d 'last month' +%Y-%m) --output /var/log/soc/billing_$(date -d 'last month' +%Y-%m).json`

---

## 11. Emergency Procedures

### 11.1 Full Pipeline Stop

```bash
systemctl stop soc-intake-wazuh soc-intake-eve soc-triage-worker@* soc-enrichment-scheduler
# Drain queues
python -m engine.queue_manager drain --timeout 300
```

### 11.2 Model Rollback

```bash
# List available adapters
python -m orchestrator.model_registry list --status promoted

# Rollback to previous
python -m orchestrator.model_registry promote --adapter-id mistral-7b-lora-v11.11 --force
```

### 11.3 Data Recovery

```bash
# Restore PostgreSQL from backup
pg_restore -U soc_admin -d local_soc /backups/soc_20250114_0200.dump

# Restore FAISS index
tar -xzf /backups/faiss_index_20250114.tar.gz -C /var/lib/soc/embeddings/

# Verify hash chain after restore
python -m engine.hash_chain_sealer verify --full
```

---

## 12. Key File Paths Reference

| Purpose | Path |
|---------|------|
| Main config | `/opt/soc/config/` |
| Logs | `/var/log/soc/` |
| Data (Redis, FAISS, hash chain, fix_backlog.json) | `/var/lib/soc/` |
| Model weights/adapters | `/opt/soc/models/` |
| Backups | `/backups/soc/` |
| Virtual env | `/opt/soc/venv/` |
| Scripts | `/opt/soc/scripts/` |

---

## 13. Version-Specific Notes (v11.11)

- **Breaking**: `sanitization_pipeline.py` now requires `config/sanitization_rules.yaml` v2 schema (adds `pii_entity_types` field)
- **New**: `quota_ledger.py` tracks per-model token usage; integrate with billing via `quota_ledger.export_billing()`
- **Changed**: `hash_chain_sealer.py` seal interval reduced from 10k to 1k events for higher audit granularity
- **Added**: `overnight/` package with self-improving pipeline; enable via `systemctl enable soc-self-improver.timer`
- **Deprecated**: `engine/intake_syslog.py` removed; migrate to `intake_wazuh` or `intake_eve`

---

**Document Version**: 11.9.0  
**Last Updated**: 2025-01-15  
**Maintainer**: SOC Engineering Team  
**Classification**: INTERNAL - OPERATIONAL# soc-autopilot Deployment Runbook v11.11

## 1. Prerequisites

### 1.1 System Requirements
- **OS**: Ubuntu 22.04 LTS or Debian 12 (Bookworm)
- **CPU**: 8+ cores (AVX2 support required for embedding inference)
- **RAM**: 32 GB minimum (64 GB recommended for pgvector HNSW indexes)
- **Storage**: 500 GB NVMe (OS + PostgreSQL) + 2 TB HDD (CMR mount for cold storage)
- **Network**: Static IP, outbound HTTPS for model provider APIs (OpenRouter, Ollama, local vLLM)

### 1.2 Required Packages (Pre-Install)
```bash
sudo apt-get update && sudo apt-get install -y \
  postgresql-16 postgresql-client-16 postgresql-16-pgvector \
  python3.11 python3.11-venv python3.11-dev \
  python3-psycopg2 \
  zstd zstdmt \
  nginx certbot python3-certbot-nginx \
  git curl jq htop iotop nvme-cli smartmontools \
  build-essential libpq-dev pkg-config \
  redis-server prometheus-node-exporter
```

### 1.3 Python Environment
```bash
python3.11 -m venv /opt/soc-slm/venv
source /opt/soc-slm/venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt  # Includes: psycopg2-binary, pgvector, numpy, torch, sentence-transformers, openai, httpx, pyyaml, prometheus-client, aiolimiter, pydantic
```

---

## 2. VM Setup

### 2.1 User & Directory Structure
```bash
sudo useradd -r -s /bin/bash -d /opt/soc-slm -m socslm
sudo mkdir -p /opt/soc-slm/{engine,orchestrator,memory,tools,overnight,config,logs,var/lib/postgresql,var/lib/redis}
sudo chown -R socslm:socslm /opt/soc-slm
# Ensure overnight directory is writable for self_improver.py fix_backlog.json writes
sudo chmod 755 /opt/soc-slm/overnight
```

### 2.2 Systemd Drop-ins (Resource Limits)
```bash
sudo mkdir -p /etc/systemd/system/{postgresql,redis,nginx}.service.d
cat <<'EOF' | sudo tee /etc/systemd/system/postgresql.service.d/override.conf
[Service]
LimitNOFILE=65536
LimitMEMLOCK=infinity
EOF
sudo systemctl daemon-reload
```

### 2.3 Kernel Tuning (pgvector HNSW)
```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/99-soc-slm.conf
vm.max_map_count=262144
vm.swappiness=10
net.core.somaxconn=4096
net.ipv4.tcp_max_syn_backlog=8192
EOF
sudo sysctl --system
```

---

## 3. PostgreSQL with pgvector Installation

### 3.1 Cluster Initialization
```bash
sudo pg_createcluster 16 main --start -d /opt/soc-slm/var/lib/postgresql/16/main
sudo -u postgres psql -c "CREATE ROLE socslm WITH LOGIN PASSWORD 'changeme_in_prod';"
sudo -u postgres psql -c "CREATE DATABASE soc_slm OWNER socslm;"
sudo -u postgres psql -c "CREATE DATABASE soc_slm_audit OWNER socslm;"
```

### 3.2 pgvector Extension & Tuning
```bash
sudo -u postgres psql -d soc_slm -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo -u postgres psql -d soc_slm -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
sudo -u postgres psql -d soc_slm -c "CREATE EXTENSION IF NOT EXISTS btree_gin;"
# Required for shared_preload_libraries = 'pg_stat_statements,auto_explain'
sudo -u postgres psql -d soc_slm -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
sudo -u postgres psql -d soc_slm -c "CREATE EXTENSION IF NOT EXISTS auto_explain;"

cat <<'EOF' | sudo tee /etc/postgresql/16/main/conf.d/99-soc-slm.conf
shared_buffers = 8GB
effective_cache_size = 24GB
maintenance_work_mem = 2GB
work_mem = 256MB
max_parallel_workers_per_gather = 4
max_parallel_maintenance_workers = 4
random_page_cost = 1.1
effective_io_concurrency = 200
wal_buffers = 64MB
min_wal_size = 2GB
max_wal_size = 8GB
checkpoint_completion_target = 0.9
max_connections = 200
shared_preload_libraries = 'pg_stat_statements,auto_explain'
auto_explain.log_min_duration = 1000
auto_explain.log_analyze = on
EOF
sudo systemctl restart postgresql@16-main
```

### 3.3 Verify pgvector
```bash
sudo -u postgres psql -d soc_slm -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
# Expected: vector | 0.7.0+
```

---

## 4. zstd Setup (Multi-threaded Compression)

### 4.1 Install zstdmt (if not in distro)
```bash
# Ubuntu 22.04 includes zstdmt via zstd package
zstd --version  # Verify 1.5.5+
```

### 4.2 Compression Profiles (Used by `engine/hash_chain_sealer.py`)
```bash
cat <<'EOF' | sudo tee /opt/soc-slm/config/zstd_profiles.yaml
profiles:
  hot:
    level: 3
    threads: 2
    window_log: 24
  warm:
    level: 9
    threads: 2
    window_log: 27
  cold:
    level: 19
    threads: 1
    window_log: 30
    long_distance_matching: true
EOF
```
> **Note**: Thread counts reduced to 2 to align with `CPUQuota=200%` (2 cores) on engine services, avoiding context-switch contention.

---

## 5. CMR HDD Mount (Cold Storage Tier)

### 5.1 Identify & Format
```bash
lsblk -o NAME,SIZE,TYPE,MODEL,SERIAL,TRAN  # Identify CMR HDD (e.g., /dev/sdb)
sudo mkfs.ext4 -L soc-cold -m 1 -E lazy_itable_init=1,lazy_journal_init=1 /dev/sdb
```

### 5.2 Mount with noatime & discard
```bash
sudo mkdir -p /mnt/cold
echo "LABEL=soc-cold /mnt/cold ext4 defaults,noatime,discard,commit=60 0 2" | sudo tee -a /etc/fstab
sudo mount -a
sudo chown socslm:socslm /mnt/cold
sudo -u socslm mkdir -p /mnt/cold/{archives,backups,vector_offload}
```

### 5.3 Verify SMART Health
```bash
sudo smartctl -a /dev/sdb | grep -E '(SMART overall|Reallocated_Sector|Current_Pending|Offline_Uncorrectable)'
```

---

## 6. Database Schema Migration (memory/schema/*.sql)

### 6.1 Migration Order (Dependency-Aware)
```bash
cd /opt/soc-slm
# Use .pgpass for security instead of PGPASSWORD env var
sudo -u socslm cp /opt/soc-slm/.pgpass ~/.pgpass && chmod 600 ~/.pgpass
sudo -u socslm psql -h localhost -U socslm -d soc_slm -f memory/schema/00_extensions.sql
sudo -u socslm psql -h localhost -U socslm -d soc_slm -f memory/schema/01_embeddings.sql
sudo -u socslm psql -h localhost -U socslm -d soc_slm -f memory/schema/02_retention_policies.sql
sudo -u socslm psql -h localhost -U socslm -d soc_slm -f memory/schema/03_rag_indexes.sql
sudo -u socslm psql -h localhost -U socslm -d soc_slm -f memory/schema/04_audit_tables.sql
sudo -u socslm psql -h localhost -U socslm -d soc_slm -f memory/schema/05_quota_ledger.sql
sudo -u socslm psql -h localhost -U socslm -d soc_slm -f memory/schema/06_hash_chain.sql
```

### 6.2 Required Content for `memory/schema/00_extensions.sql`
```sql
-- memory/schema/00_extensions.sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE SCHEMA IF NOT EXISTS memory;
GRANT ALL ON SCHEMA memory TO socslm;
ALTER DEFAULT PRIVILEGES IN SCHEMA memory GRANT ALL ON TABLES TO socslm;
ALTER DEFAULT PRIVILEGES IN SCHEMA memory GRANT ALL ON SEQUENCES TO socslm;
```

### 6.3 Verify Migration
```bash
sudo -u socslm psql -h localhost -U socslm -d soc_slm -c "\dt memory.*"
# Expected tables: embeddings, retention_policies, rag_chunks, audit_events, quota_ledger, hash_chain
```

### 6.4 Create HNSW Indexes (Post-Load)
```bash
sudo -u socslm psql -h localhost -U socslm -d soc_slm -c "
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_embeddings_vector_hnsw
ON memory.embeddings USING hnsw (vector vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
"
```
> **Note**: `maintenance_work_mem = 2GB` (set in 3.2) is sufficient for HNSW build on datasets up to ~50M vectors. Monitor for OOM if scaling beyond.

---

## 7. Config File Placement

### 7.1 Main Configuration (`/opt/soc-slm/config/production.yaml`)
```yaml
# /opt/soc-slm/config/production.yaml
database:
  host: "localhost"
  port: 5432
  name: "soc_slm"
  user: "socslm"
  password: "${DB_PASSWORD}"
  pool_size: 20
  max_overflow: 10

redis:
  host: "localhost"
  port: 6379
  db: 0
  max_connections: 50

engine:
  intake_wazuh:
    listen_port: 5140
    batch_size: 500
    flush_interval_ms: 100
  sanitization_pipeline:
    pii_patterns_file: "config/pii_patterns.yaml"
    max_event_size_mb: 10
  slm_triage_worker:
    model: "local-slm-v11.11"
    batch_size: 32
    timeout_seconds: 30
  quota_ledger:
    daily_limit: 100000
    burst_limit: 5000
    provider: "openrouter"
  queue_manager:
    max_queue_size: 100000
    persistence: "redis"
  enrichment_scheduler:
    interval_seconds: 300
    ioc_sources: ["abuse.ch", "otx", "misp"]
  ioc_extractor:
    enable_yara: true
    yara_rules_path: "config/yara/"
  intake_eve:
    listen_port: 5141
    json_only: true
  hash_chain_sealer:
    interval_seconds: 60
    zstd_profile: "warm"
    cold_storage_path: "/mnt/cold/archives"

orchestrator:
  context_stitcher:
    max_context_tokens: 8192
    embedding_model: "bge-large-en-v1.5"
  model_registry:
    providers:
      - name: "openrouter"
        api_key: "${OPENROUTER_API_KEY}"
        models: ["anthropic/claude-3.5-sonnet", "meta-llama/llama-3.1-70b"]
        fallback_order: 1
      - name: "ollama"
        base_url: "http://localhost:11434"
        models: ["llama3.1:70b", "qwen2.5:72b"]
        fallback_order: 2
      - name: "vllm"
        base_url: "http://localhost:8000"
        models: ["local-slm-v11.11"]
        fallback_order: 3

memory:
  embeddings:
    model: "BAAI/bge-large-en-v1.5"
    device: "cuda"
    batch_size: 64
    dimension: 1024
  retention:
    hot_days: 7
    warm_days: 90
    cold_days: 2555
    archive_path: "/mnt/cold/vector_offload"

overnight:
  self_improver:
    enabled: true
    schedule_cron: "0 2 * * *"
    max_iterations: 5
    fix_backlog_path: "overnight/fix_backlog.json"
    llm_client:
      rate_limit_rpm: 60
      rate_limit_tpm: 100000
      circuit_breaker_threshold: 5
      circuit_breaker_timeout: 300
    openrouter_quota:
      daily_limit: 500000
      warning_threshold: 0.8

logging:
  level: "INFO"
  format: "json"
  output: "/opt/soc-slm/logs/soc-slm.log"
  rotation: "daily"
  retention_days: 30

metrics:
  prometheus_port: 9090
  pushgateway: "http://localhost:9091"
```

### 7.2 Environment File (`/opt/soc-slm/.env.production`)
```bash
cat <<'EOF' > /opt/soc-slm/.env.production
DB_PASSWORD="changeme_in_prod"
OPENROUTER_API_KEY="sk-or-v1-..."
REDIS_PASSWORD=""
GRAFANA_ADMIN_PASSWORD="changeme"
EOF
chmod 600 /opt/soc-slm/.env.production
chown socslm:socslm /opt/soc-slm/.env.production
```

### 7.3 PostgreSQL Password File (`/opt/soc-slm/.pgpass`)
```bash
cat <<'EOF' > /opt/soc-slm/.pgpass
localhost:5432:soc_slm:socslm:changeme_in_prod
localhost:5432:soc_slm_audit:socslm:changeme_in_prod
EOF
chmod 600 /opt/soc-slm/.pgpass
chown socslm:socslm /opt/soc-slm/.pgpass
```

### 7.4 PII Patterns (`/opt/soc-slm/config/pii_patterns.yaml`)
```yaml
patterns:
  - name: "ipv4"
    regex: "\\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\b"
    replacement: "[IP_REDACTED]"
  - name: "email"
    regex: "\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b"
    replacement: "[EMAIL_REDACTED]"
  - name: "credit_card"
    regex: "\\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12})\\b"
    replacement: "[CC_REDACTED]"
```

### 7.5 Log Rotation (`/etc/logrotate.d/soc-slm`)
```bash
cat <<'EOF' | sudo tee /etc/logrotate.d/soc-slm
/opt/soc-slm/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 socslm socslm
    sharedscripts
    postrotate
        systemctl reload soc-slm-engine@intake_wazuh > /dev/null 2>&1 || true
        systemctl reload soc-slm-engine@intake_eve > /dev/null 2>&1 || true
    endscript
}
EOF
```

---

## 8. Service Startup Order (systemd Units)

### 8.1 Create Service Files
```bash
# /etc/systemd/system/soc-slm-engine@.service
cat <<'EOF' | sudo tee /etc/systemd/system/soc-slm-engine@.service
[Unit]
Description=SOC SLM Engine - %i
After=network.target postgresql@16-main.service redis.service
Requires=postgresql@16-main.service redis.service

[Service]
Type=exec
User=socslm
Group=socslm
WorkingDirectory=/opt/soc-slm
EnvironmentFile=/opt/soc-slm/.env.production
ExecStart=/opt/soc-slm/venv/bin/python -m engine.%i
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3
LimitNOFILE=65536
MemoryLimit=8G
CPUQuota=200%

[Install]
WantedBy=multi-user.target
EOF

# /etc/systemd/system/soc-slm-orchestrator@.service
cat <<'EOF' | sudo tee /etc/systemd/system/soc-slm-orchestrator@.service
[Unit]
Description=SOC SLM Orchestrator - %i
After=network.target soc-slm-engine@queue_manager.service
Requires=soc-slm-engine@queue_manager.service

[Service]
Type=exec
User=socslm
Group=socslm
WorkingDirectory=/opt/soc-slm
EnvironmentFile=/opt/soc-slm/.env.production
ExecStart=/opt/soc-slm/venv/bin/python -m orchestrator.%i
Restart=on-failure
RestartSec=5
LimitNOFILE=32768
MemoryLimit=4G

[Install]
WantedBy=multi-user.target
EOF

# /etc/systemd/system/soc-slm-memory@.service
cat <<'EOF' | sudo tee /etc/systemd/system/soc-slm-memory@.service
[Unit]
Description=SOC SLM Memory - %i
After=network.target postgresql@16-main.service
Requires=postgresql@16-main.service

[Service]
Type=exec
User=socslm
Group=socslm
WorkingDirectory=/opt/soc-slm
EnvironmentFile=/opt/soc-slm/.env.production
ExecStart=/opt/soc-slm/venv/bin/python -m memory.%i
Restart=on-failure
RestartSec=10
LimitNOFILE=32768
MemoryLimit=16G

[Install]
WantedBy=multi-user.target
EOF

# /etc/systemd/system/soc-slm-overnight.service
cat <<'EOF' | sudo tee /etc/systemd/system/soc-slm-overnight.service
[Unit]
Description=SOC SLM Overnight Self-Improving Pipeline
After=network.target postgresql@16-main.service redis.service
Requires=postgresql@16-main.service redis.service

[Service]
Type=oneshot
User=socslm
Group=socslm
WorkingDirectory=/opt/soc-slm
EnvironmentFile=/opt/soc-slm/.env.production
ExecStart=/opt/soc-slm/venv/bin/python -m overnight.self_improver
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# /etc/systemd/system/soc-slm-overnight.timer
cat <<'EOF' | sudo tee /etc/systemd/system/soc-slm-overnight.timer
[Unit]
Description=Run overnight self-improver daily at 02:00

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
EOF
```

### 8.2 Enable & Start in Order
```bash
sudo systemctl daemon-reload

# Phase 1: Infrastructure (Redis MUST be active before engine services)
sudo systemctl enable --now postgresql@16-main redis nginx
sudo systemctl is-active --quiet redis || { echo "Redis failed to start"; exit 1; }

# Phase 2: Engine (dependency order matters)
sudo systemctl enable --now soc-slm-engine@queue_manager
sudo systemctl enable --now soc-slm-engine@quota_ledger
sudo systemctl enable --now soc-slm-engine@intake_wazuh
sudo systemctl enable --now soc-slm-engine@intake_eve
sudo systemctl enable --now soc-slm-engine@sanitization_pipeline
sudo systemctl enable --now soc-slm-engine@ioc_extractor
sudo systemctl enable --now soc-slm-engine@enrichment_scheduler
sudo systemctl enable --now soc-slm-engine@slm_triage_worker
sudo systemctl enable --now soc-slm-engine@hash_chain_sealer

# Phase 3: Orchestrator
sudo systemctl enable --now soc-slm-orchestrator@context_stitcher
sudo systemctl enable --now soc-slm-orchestrator@model_registry

# Phase 4: Memory
sudo systemctl enable --now soc-slm-memory@embeddings
sudo systemctl enable --now soc-slm-memory@retention

# Phase 5: Overnight Pipeline (v11.11)
sudo systemctl enable --now soc-slm-overnight.timer

# Verify all active
systemctl list-units 'soc-slm-*' --state=active
```

---

## 9. Smoke Tests (tools/*_check.py)

### 9.1 Run All Health Checks
```bash
cd /opt/soc-slm
source venv/bin/activate

# Database connectivity & pgvector
python tools/db_check.py --dsn "postgresql://socslm:${DB_PASSWORD}@localhost:5432/soc_slm" --test-vector

# Redis connectivity
python tools/redis_check.py --host localhost --port 6379

# Engine modules
python tools/engine_check.py --module intake_wazuh --port 5140
python tools/engine_check.py --module intake_eve --port 5141
python tools/engine_check.py --module sanitization_pipeline --test-pii
python tools/engine_check.py --module slm_triage_worker --model local-slm-v11.11
python tools/engine_check.py --module quota_ledger --provider openrouter
python tools/engine_check.py --module queue_manager --depth-check
python tools/engine_check.py --module enrichment_scheduler --test-ioc
python tools/engine_check.py --module ioc_extractor --test-yara
python tools/engine_check.py --module hash_chain_sealer --verify-chain

# Orchestrator modules
python tools/orchestrator_check.py --module context_stitcher --test-embedding
python tools/orchestrator_check.py --module model_registry --test-fallback

# Memory modules
python tools/memory_check.py --module embeddings --model BAAI/bge-large-en-v1.5 --dim 1024
python tools/memory_check.py --module retention --test-policy

# Overnight pipeline (v11.11)
python tools/overnight_check.py --module self_improver --dry-run
python tools/overnight_check.py --module llm_client --test-fallback --test-rate-limit
python tools/overnight_check.py --module openrouter_quota --check-daily
python tools/overnight_check.py --module fix_backlog --validate-json
```

### 9.2 Expected Smoke Test Output
```
[PASS] db_check: Connection OK, pgvector 0.7.0, HNSW index exists
[PASS] redis_check: PING OK, 50/50 connections available
[PASS] engine_check:intake_wazuh: Listening on 0.0.0.0:5140
[PASS] engine_check:intake_eve: Listening on 0.0.0.0:5141
[PASS] engine_check:sanitization_pipeline: PII redaction functional (5/5 patterns)
[PASS] engine_check:slm_triage_worker: Model loaded, inference <500ms
[PASS] engine_check:quota_ledger: OpenRouter quota 487,231/500,000 remaining
[PASS] engine_check:queue_manager: Depth 0/100000, Redis backend healthy
[PASS] engine_check:enrichment_scheduler: 3 IOC sources configured
[PASS] engine_check:ioc_extractor: YARA rules loaded (247 rules)
[PASS] engine_check:hash_chain_sealer: Chain verified, last seal 2025-01-15T02:00:00Z
[PASS] orchestrator_check:context_stitcher: Embedding dim 1024, context window 8192
[PASS] orchestrator_check:model_registry: 3 providers, fallback chain verified
[PASS] memory_check:embeddings: Model loaded on CUDA, batch 64 OK
[PASS] memory_check:retention: Policies active (hot:7d, warm:90d, cold:2555d)
[PASS] overnight_check:self_improver: Dry-run completed, 0 fixes generated
[PASS] overnight_check:llm_client: Fallback chain OpenRouter->Ollama->vLLM tested
[PASS] overnight_check:llm_client: Rate limit 60 RPM / 100k TPM enforced
[PASS] overnight_check:openrouter_quota: Daily 500k, current 2.3%, warning at 80%
[PASS] overnight_check:fix_backlog: JSON valid, 12 pending fixes
```

---

## 10. Spike Validation (R-001 through R-117)

### 10.1 Validation Script
```bash
cd /opt/soc-slm
python tools/spike_validator.py --requirements docs/requirements_spike_v11.11.yaml --output spike_report.json
```

### 10.2 Key Spike Requirements (Subset)
| ID | Requirement | Validation Method |
|----|-------------|-------------------|
| R-001 | Wazuh JSON intake at 10k EPS | `tools/load_test.py --module intake_wazuh --rate 10000 --duration 60` |
| R-002 | Eve JSON intake at 5k EPS | `tools/load_test.py --module intake_eve --rate 5000 --duration 60` |
| R-003 | PII redaction <5ms/event | `tools/latency_check.py --module sanitization_pipeline --p99 5` |
| R-004 | SLM triage <30s p99 | `tools/latency_check.py --module slm_triage_worker --p99 30000` |
| R-005 | Quota ledger accuracy ±0.1% | `tools/quota_check.py --precision 0.001` |
| R-006 | Queue persistence survive restart | `tools/chaos_test.py --kill queue_manager --verify-depth` |
| R-007 | Enrichment adds ≥3 IOC fields | `tools/enrichment_check.py --min-fields 3` |
| R-008 | IOC extraction recall >95% | `tools/ioc_recall_test.py --dataset mitre-attack --threshold 0.95` |
| R-009 | Hash chain immutability | `tools/hash_chain_verify.py --tamper-test` |
| R-010 | Context stitcher token budget | `tools/context_check.py --max-tokens 8192 --verify-truncation` |
| R-011 | Model registry fallback <2s | `tools/fallback_latency.py --max-failover 2000` |
| R-012 | Embedding inference >1k/sec | `tools/embedding_throughput.py --target 1000` |
| R-013 | Retention policy execution | `tools/retention_dryrun.py --verify-deletion` |
| R-014 | pgvector HNSW recall@10 >0.9 | `tools/vector_recall.py --k 10 --threshold 0.9` |
| R-015 | Cold storage offload >100MB/s | `tools/cold_offload_bench.py --target 100` |
| R-016 | zstd compression ratio >3:1 | `tools/compression_ratio.py --profile warm --min-ratio 3` |
| R-017 | Overnight pipeline completes <4h | `tools/overnight_timing.py --max-hours 4` |
| R-018 | Self-improver generates valid patches | `tools/patch_validator.py --syntax-check --test-apply` |
| R-019 | LLM client multi-provider fallback | `tools/llm_fallback_test.py --providers 3 --verify-order` |
| R-020 | Rate limit enforcement (RPM/TPM) | `tools/rate_limit_test.py --rpm 60 --tpm 100000` |
| R-021 | Circuit breaker activation | `tools/circuit_breaker_test.py --threshold 5 --timeout 300` |
| R-022 | OpenRouter quota tracking | `tools/quota_tracking_test.py --daily-limit 500000` |
| R-023 | Fix backlog JSON schema valid | `tools/json_schema_check.py --schema overnight/fix_backlog.schema.json` |
| R-024 | End-to-end alert to ticket <60s | `tools/e2e_latency.py --p99 60000` |
| R-025 | High availability (single node) | `tools/ha_check.py --single-node --mttr 300` |

### 10.3 Full Validation Command
```bash
# Run all 117 spike validations (takes ~45 minutes)
python tools/spike_validator.py \
  --requirements docs/requirements_spike_v11.11.yaml \
  --parallel 4 \
  --timeout 3600 \
  --output /opt/soc-slm/logs/spike_validation_$(date +%Y%m%d_%H%M%S).json \
  --junit /opt/soc-slm/logs/spike_validation_$(date +%Y%m%d_%H%M%S).xml
```

### 10.4 Acceptance Criteria
- **All 117 spikes must PASS** for production deployment
- Any FAIL blocks deployment; investigate via `spike_report.json`
- Re-run failed spikes individually: `python tools/spike_validator.py --only R-042`

---

## 11. v11.11 Overnight Self-Improving Pipeline

### 11.1 Pipeline Components
```
overnight/
├── self_improver.py          # Main orchestrator
├── llm_client.py             # Multi-provider LLM client with fallback & rate limiting
├── openrouter_quota.py       # Quota tracking & alerting
├── fix_backlog.json          # Persistent backlog of code fixes
├── fix_backlog.schema.json   # JSON schema validation
└── patches/                  # Generated patch files (git apply compatible)
```

### 11.2 self_improver.py Flow
```python
# Simplified flow in overnight/self_improver.py
async def run_pipeline():
    # 1. Load fix_backlog.json
    backlog = load_backlog("overnight/fix_backlog.json")
    
    # 2. Analyze production metrics (error rates, latency, quota usage)
    metrics = await collect_metrics(prometheus_url="http://localhost:9090")
    
    # 3. Generate improvement hypotheses via LLM
    hypotheses = await llm_client.generate_hypotheses(
        metrics=metrics,
        codebase_context=get_codebase_context(),
        max_iterations=config.max_iterations
    )
    
    # 4. Validate hypotheses (syntax, tests, security)
    validated = await validate_hypotheses(hypotheses)
    
    # 5. Create patches & append to backlog
    for fix in validated:
        patch = create_patch(fix)
        backlog.append({"patch": patch, "timestamp": utcnow(), "status": "pending"})
    
    # 6. Save updated backlog
    save_backlog(backlog, "overnight/fix_backlog.json")
    
    # 7. Emit metrics
    push_metrics({"fixes_generated": len(validated), "backlog_size": len(backlog)})
```

### 11.3 llm_client.py Multi-Provider Fallback with Circuit Breaker Persistence
```python
# overnight/llm_client.py - Complete implementation
import asyncio
import time
import json
import redis.asyncio as redis
from aiolimiter import AsyncLimiter
from dataclasses import dataclass
from typing import Optional, List
from

## Recent Architectural Updates (v11.11.x)

### Environment Variables
The `TriageQueueManager` is now fully configurable via environment variables. If not provided, it falls back to safe defaults:
- `QUEUE_LEASE_INTERVAL`: Lease duration in seconds (default: `900`)
- `QUEUE_MAX_ATTEMPTS`: Max retry attempts before marking failed (default: `3`)
- `QUEUE_EMERGENCY_DEPTH`: Backpressure threshold for low-priority jobs (default: `1000`)
- `RETENTION_DAYS`: Days to retain partition data before archiving (default: `90`)

### Optional Dependencies
- **`psycopg2`** (or `psycopg2-binary`) is now an **optional** dependency. It is only required if you are actively using PostgreSQL features (e.g., `enrichment_scheduler.py` or `retention.py`). The codebase will load and run in SQLite-only environments without it.

### Schema Management
- The database initialization schema has been extracted from Python code into `engine/schema.sql` for better version control and readability.
