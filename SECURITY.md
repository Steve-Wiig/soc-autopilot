# Security Policy

## Scope

SOC-Autopilot is an experimental, local-first security orchestration and autonomous software-maintenance project.

Security issues involving any of the following should be treated as security-sensitive:

- safety-gate bypasses
- unauthorized autonomous code mutation
- unsafe promotion or self-approval
- production cloud-routing violations
- telemetry or audit-integrity failures
- credential or secret exposure
- trust-boundary bypasses
- worker/verification impersonation or replay

## Reporting

Please report suspected vulnerabilities privately rather than publishing exploit details before remediation.

Include, where possible:

- affected component or file
- reproduction steps
- observed impact
- relevant sanitized logs or test output

Do not include credentials, API keys, or other secrets.

## Security principles

SOC-Autopilot is designed around these principles:

1. External content is data, not authority.
2. LLM output is untrusted and must not authorize itself.
3. Deterministic policy gates consequential actions.
4. Autonomous development changes require tests and verification.
5. Promotion state must reflect what actually happened.
6. Telemetry must distinguish proposals, reviews, tests, canaries, and merged changes.
7. Human approval remains authoritative where required.

## Project status

This project is experimental/research software.

It should not be treated as an unsupervised production SOC operator merely because individual components or laboratory workflows have been validated.

See [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) for the detailed security model.
