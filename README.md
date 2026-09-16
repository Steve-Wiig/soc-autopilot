# SOC Autopilot

A secure, cryptographically verified, and strictly sandboxed autonomous development pipeline. 

This system allows Large Language Models (LLMs) to propose and implement code changes **without** granting them direct commit access, unrestricted filesystem access, or the ability to bypass human review.

+++

## Architecture Overview

This system uses a defense-in-depth approach to ensure AI-generated code is safe, verified, and strictly bounded.

1. **Bounded Worker**: Aider runs with `--no-git` and `--no-auto-commits`. It cannot alter Git history.
2. **Explicit Allowlist**: It is only permitted to read/modify files explicitly passed via `--files`. Touching unauthorized paths causes a hard failure.
3. **Bubblewrap Sandboxing**: The worker executes in a strict Linux namespace with read-only system binaries and an isolated temporary filesystem. It cannot access host `.env` files or SSH keys.
4. **Cryptographic Quorum**: Proposals must be independently reviewed and signed by 3 distinct Ed25519 identities. 
5. **Zero Auto-Merges**: The state machine strictly halts at `PENDING_HUMAN_MERGE`. Output is saved as a verifiable `.patch` file for human review.

+++

## How It Works

### The Entrypoint
```bash
python3 scripts/propose_code.py --auto \
  "Add input validation to the user login handler" \
  --files engine/auth_handler.py tests/test_auth.py
```

### The Overnight Runner
`overnight.sh` provides a safe, automated loop:
1. Creates a disposable branch (e.g., `auto/overnight-YYYYMMDD`). Refuses to run on `main`/`master`.
2. Generates patches for defined tasks.
3. Applies the patch and runs `pytest`.
4. **Rollback on Failure**: If tests fail, the branch is instantly reset, and the failure is logged.
5. Generates a `proposals/MORNING_REPORT.md`.

+++

## Operational Requirements
- Python 3.10+
- Bubblewrap (`apt install bubblewrap`)
- Aider (`pipx install aider-chat` or `vu`)
- Valid API keys in `.env`
