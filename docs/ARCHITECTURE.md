# SOC-Autopilot: Architecture & Hardening Log

*Last updated: September 10, 2026*

This document outlines the current distributed architecture of the `soc-autopilot` swarm, the hardware optimizations applied to prevent system hangs, and the data flow between the Ubuntu VM and the Raspberry Pi Critic.

## 1. Hardware & Infrastructure
- **Primary Node (Ubuntu VM):** Handles patch generation (`pi_generator.py`), consensus gating, and dashboard telemetry. Migrated from a flaky NAS mount (`/mnt/backup-nas`) to a local USB HDD to eliminate D-state kernel panics caused by unresponsive VFS I/O.
- **Edge Critic (Raspberry Pi 4 @ 192.168.1.31):** Hosts the local LLM (Ollama) and the `pi_consumer.py` service. Evaluates generated patches for syntax, logic, and security flaws before they are applied to the codebase.

## 2. Pi Critic Optimizations
To prevent the Pi from thermal throttling and hallucinating rejections, the following configurations were applied:
- **Resource Reclamation:** Disabled Open WebUI (freed ~850MB RAM).
- **Model Persistence:** Configured Ollama via systemd drop-in with `OLLAMA_KEEP_ALIVE=-1`. This forces the LLM to stay permanently loaded in RAM, eliminating 30-second "cold start" penalties on every review.
- **Model Selection:** Standardized on `qwen2.5-coder:3b`. It strikes the optimal balance between logic comprehension and inference speed (~30s per patch).
- **Prompt Engineering:** Replaced the "Hostile Security Auditor" prompt (which caused small models to hallucinate bugs to fulfill their persona) with an "Objective Senior Engineer" prompt.
- **Thermal Pacing:** Added `time.sleep(2)` to the `pi_consumer.py` loop to give the CPU a breather between inferences, preventing thermal throttling during large backlog clearances.

## 3. Dashboard Telemetry (`tools/dashboard.py`)
The dashboard was hardened to remain responsive even when network drives or background workers are unresponsive.
- **NAS Guard:** Uses `/proc/mounts` to verify if the NAS is actually mounted before attempting directory scans.
- **Redis Telemetry:** Replaced the phantom `pi-worker` systemd check with a live query to the Pi's Redis queue depth (`pi_critic_queue` and `pi_critic_results`).
- **Timeouts:** Added execution timeouts to the Consensus Gate (60s) and the PyTest suite (120s) to prevent infinite terminal hangs.
- **`--fast` Flag:** Added an argparse flag to skip the heavy test suite for rapid status checks (`python3 tools/dashboard.py --fast`).

## 4. Data Flow & Automation
1. **Generation:** `pi_generator.py` (VM) creates unified diffs and writes them to `pi_patches.jsonl`.
2. **Dispatch:** `pi_idle_reviewer.py` (VM) reads the JSONL file and pushes jobs to the Pi's `pi_critic_queue` in Redis.
3. **Review:** `pi_consumer.service` (Pi) pops jobs, evaluates them via Ollama (3B model), and pushes verdicts to `pi_critic_results`.
4. **Ingestion:** A cron job runs `tools/pi_redis_ingestor.py` every 5 minutes to pull Pi results from Redis and append them to the local `improvement_ledger.jsonl`.
5. **Consensus:** `process_oracle.py` reads the ledger, applies verified patches, and updates the scorecard.
