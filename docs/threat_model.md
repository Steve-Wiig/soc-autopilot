# SOC Autopilot Swarm Threat Model

**Document Threat Model for:** SOC Autopilot Swarm Distribution  
**Last Updated:** 2025-08-22  
**Threat Model Author:** Staff Security Architect  

## 1. System Context

The SOC Autopilot Swarm is a distributed security orchestration system comprising:
- Worker nodes executing development candidate fixes
- Central coordination via Redis-backed backlog/queues
- LLM providers for code analysis and remediation
- API gateways for external integrations (TheHive, SIEM, etc.)
- Edge devices for remote asset monitoring

## 2. Trust Boundaries

| Boundary | Components | Trust Assumption |
|---|---|---|
| **LLM Inference** | Provider APIs, prompt payloads | Partial trust; untrusted input |
| **Message Layer** | Redis, quorum queues, backlog | Must be secured; often deployed as trusted internal network |
| **Credential Management** | API keys, service tokens | High-value targets; must be isolated |
| **Edge Perimeter** | Sensor/agent devices, kernel agents | Physically distributed; zero trust for payloads |

## 3. Attack Vectors

### A. LLM Poisoning (Malicious Payloads)

**Description:** An attacker crafts malicious prompts or code payloads injected into the LLM inference pipeline, causing unintended actions, data exfiltration, or model hallucination that compromises the swarm's integrity.

**Entry Points:**
- Unvalidated prompt inputs from user-facing interfaces
- Unsanitized IOC data passed to LLM context
- Compromised third-party training data or model weights

**Impact:** Arbitrary code execution in downstream processes, false positive/negative security decisions, reputational damage.

### B. Redis Compromise (Backlog Injection)

**Description:** Redis is used as the central backlog/queue for worker tasks. An attacker injects malicious entries, causing workers to process attacker-controlled payloads, pivot internally, or exfiltrate data.

**Entry Points:**
- Unauthenticated Redis access (default no-password config)
- Unsanitized ZSET/SKEY injection via worker vote adapters
- Backlog poisoning through compromised worker identities

**Impact:** Full swarm compromise, backlog manipulation, lateral movement into internal networks.

### C. API Key Leakage

**Description:** Cryptographic material (Ed25519 keys, API tokens, service credentials) accidentally committed to version control, logged, or transmitted in cleartext.

**Entry Points:**
- Environment variable dumping in Docker/CI configs
- Log output containing `WorkerVote` signatures or `AdvisoryIdentity` hashes
- Hardcoded keys in worker identity serializers

**Impact:** Full authentication bypass, unauthorized sign-off on malicious fixes, credential stuffing across services.

### D. Edge Device Trust

**Description:** Edge agents/kernels report status and receive commands. Without strong mutual authentication, an attacker impersonates legitimate edge devices or injects false telemetry.

**Entry Points:**
- Unverified firmware update payloads
- Plaintext telemetry transmission
- Missing or weak key rotation policies

**Impact:** Physical asset compromise, false security posture, pivot into protected networks.

## 4. Mitigations (Top 3 Risks)

### Mitigation 1: LLM Poisoning Defenses

**Input Validation & Schema Enforcement**
