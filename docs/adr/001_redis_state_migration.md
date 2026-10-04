# Architecture Decision Record: 001_redis_state_migration.md

Status: Accepted

Context: The system currently persists worker state and deduplication queues using local JSONL files. This approach has proven fragile due to race conditions during concurrent access, lack of atomic operations, and vulnerability to process crashes that leave state in inconsistent or lost states. As the swarm scales, JSONL file locking becomes a bottleneck, and recovery from crashes requires manual intervention or complex replay logic. There is a need for a reliable, distributed, crash-proof queue and deduplication mechanism that survives process restarts and supports concurrent workers.

Decision: Replace the local JSONL-based state management with Redis-backed structures. Utilize Redis lists for crash-proof work queues (using RPOPLPUSH or BRPOP for atomic consumption), and Redis Sets or Bloom filters for efficient deduplication of advisories/work items. Leverage Redis persistence modes (RDB or AOF) to ensure durability, and implement health checks and fallback strategies. All existing JSONL readers will be wrapped with Redis adapters to maintain backward compatibility during transition.

Consequences:
- Positive: Crash-safe state persistence, atomic queue operations, significant performance improvement for concurrent workers, built-in TTL support for automatic expiration of stale entries, easier monitoring via Redis metrics.
- Negative: Introduces a new dependency on Redis, requiring infrastructure setup and monitoring. Existing deployments without Redis will need migration scripts. Network partitions between workers and Redis must be handled gracefully with appropriate timeouts and fallback behaviors.
