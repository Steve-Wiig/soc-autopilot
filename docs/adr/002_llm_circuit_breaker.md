# Architecture Decision Record: 002_llm_circuit_breaker.md

Status: Accepted

Context: The system integrates multiple LLM providers, including free-tier models with variable rate limits and degraded performance under load. Recent observations show that free-tier models can silently exceed quota, return errors, or exhibit high latency, causing cascading failures and budget overruns. There is a need to protect API quota and system stability from degraded or misbehaving models without manually monitoring every request.

Decision: Implement a circuit breaker pattern around LLM provider calls. The breaker monitors success rate, latency, and error rates per provider/model. When thresholds are crossed (e.g., >50% error rate or latency > 2s for 10 consecutive calls), the breaker trips and routes requests to healthy providers or returns cached/graceful fallbacks. A half-open state allows probe requests after a cooldown to verify recovery. Metrics and state are stored in Redis for consistency across workers. All provider calls go through this wrapper, ensuring automatic protection and recovery.

Consequences:
- Positive: Automatic protection against quota exhaustion and degraded model performance, reduced manual monitoring, improved system stability, graceful degradation. 
- Negative: Added latency for circuit check, complexity in threshold tuning, potential temporary unavailability if breaker trips incorrectly, dependency on healthy provider alternatives.
