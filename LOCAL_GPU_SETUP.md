# Local GPU Transition Plan

This document outlines the exact steps required to transition the SOC Autopilot
from cloud-based API providers (OpenRouter) to a fully local, air-gapped LLM
inference stack once your GPU hardware (eg., RTX 4090, A6000) arrives.

### 1. Hardware Requirements
- **VRAM:** Minimum 24GB VRAM for 14B-27B models with large context windows.
- **System RAM:** 64GB+ recommended for large context windows (32k+ tokens).

### 2. Software Setup

### Install Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Pull the Target Model
For autonomous coding tasks, we recommend the Qwen 2.5 Coder series:
```bash
# 14B Model (Requires ~10GB VRAM)
ollama pull qwen2.5-coder:14b

# 32B Model (Requires ~20GB VRAM)
ollama pull qwen2.5-coder:32b
```

### 3. Configuration Changes

### Update `.env`
```bash
# Add Ollama base URL
OLLAMA_API_BASE=HTTP://localhost:11434

# Disable cloud providers
SOC_AUTOPILOT_DEVELOPMENT_CLOUD=0
```

### Update `engine/aider_provider.py`Change the hardcoded model string to route through LiteLLM's Ollama provider:
```python
# Change this:
openrouter_model = "openrouter/qwen/qwen-2.5-coder-7b-instruct:free"

# To this:
openrouter_model = "ollama/qwen2.5-coder:32b"
```

### 4. Adjusting Timeouts
Local inference can be faster or slower depending on the hardware. Adjust the
timeout in `engine/aider_development_worker.py` accordingly:
```python
# If your GPU is very fast, you can reduce this:
timeout: int = 300

# If generating massive multi-file diffs, you may need to increase it:
timeout: int = 900
```

### 5. Running the Local Overnight Loop
Once configured, the `overnight.sh` script requires NO changes. It will 
automatically route all Aider requests through your local Ollama instance, 
achieving 100% air-gapped, zero-cost autonomous development.
