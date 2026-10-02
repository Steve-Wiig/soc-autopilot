
---

## 🏗️ Current Deployment Architecture (v2.0)

The system has evolved from a collection of scripts into a hardened, production-grade autonomous agent network.

### 1. The Control VM (Systemd Managed)
All core processes are managed by `systemd --user` with `linger` enabled, ensuring they start at boot and auto-restart on failure:
- **soc-swarm.service**: The 7B local model loop. Features QA-driven file selection, meaningful-change commit guards (>5 lines), and consecutive failure alerting.
- **soc-phone-reviewer.service**: The 3B Android worker. Features adaptive prompting to prevent documentation drift and auto-circuit breakers on API failures.
- **soc-dashboard-watchdog.service**: Monitors the dashboard process and auto-restarts it if it becomes stale.
- **soc-phone-keepalive.service**: Sends a lightweight heartbeat to the phone every 8 minutes to prevent Android OS from evicting the 3B model from RAM.

### 2. Safety & Self-Preservation Mechanisms
- **Git Sanity Check**: Every swarm cycle verifies the working tree is clean and on the correct branch. Forces `git reset --hard` and `git clean -fdx` if corrupted.
- **Disk Defense**: A daily cron job (`~/log_rotator.sh`) truncates logs >50MB and vacuums systemd journals. The swarm aggressively purges `.worktrees` if root disk exceeds 85%.
- **Skip List Overflow**: Automatically prunes the oldest 25 entries if the blacklist exceeds 50 files, preventing the swarm from stalling.

### 3. External API Usage (OpenRouter)
- **Strict Free-Tier Enforcement**: All OpenRouter calls explicitly append `:free` to the model name (e.g., `nvidia/nemotron-3-ultra-550b-a55b:free`).
- **Quota Ledger**: Enforces a hard limit to stay within the 1,000 requests/day free tier allowance.
- **Sanitization**: All code snippets and tracebacks are passed through `sanitize_for_external_api()` to redact secrets, API keys, and high-entropy tokens before leaving the Control VM.

