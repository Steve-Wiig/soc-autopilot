# LOCAL-SOC-SLM Master Documentation Bundle (TEST COPY)

**Generated:** 2026-08-23 22:08:46  
**Source:** v11.11.0 Blueprint  
**Status:** REVIEW COPY — not yet promoted to final  
**Total Documents:** 6/6  
**Combined Line Count:** 4084 lines

---

This document combines all operational documentation for the LOCAL-SOC-SLM platform into a single reference bundle optimized for large-context LLM consumption.


---

# Architecture

*Source: `docs/ARCHITECTURE.md` (741 lines)*

# LOCAL-SOC-SLM Architecture Document (v11.11)

## Overview

LOCAL-SOC-SLM is a local Security Operations Center automation platform that processes security alerts from Wazuh, enriches them through local SLM triage, and writes actionable cases to TheHive. Version 11.9 introduces the **Overnight Self-Improving Pipeline**, which leverages historical case outcomes to refine detection logic and prompt engineering, supported by a resilient multi-provider LLM client with quota management.

---

## 1. End-to-End Data Flow: Wazuh Intake → TheHive Writeback

```mermaid
flowchart TD
    subgraph INTAKE["Intake Layer"]
        WZ[("Wazuh Manager\n/var/ossec/logs/alerts/alerts.json")]
        IW["engine/intake_wazuh.py\nWazuhIntakeClient"]
        IE["engine/intake_eve.py\nEVEIntakeClient"]
        KAFKA[("Kafka Topic\nwazuh-alerts")]
    end

    subgraph SANITIZE["Sanitization Pipeline"]
        SP["engine/sanitization_pipeline.py\nSanitizationPipeline"]
        QUAR[("Quarantine Store\n/var/lib/soc/quarantine/")]
        HCS["engine/hash_chain_sealer.py\nHashChainSealer"]
    end

    subgraph QUEUE["Queue Management"]
        QM["engine/queue_manager.py\nQueueManager"]
        PQ[("Priority Queue\nRedis Streams")]
        BP["Backpressure Controller"]
        SHED["Load Shedder"]
    end

    subgraph TRIAGE["SLM Triage Worker"]
        STW["engine/slm_triage_worker.py\nSLMTriageWorker"]
        MR["orchestrator/model_registry.py\nModelRegistry"]
        CS["orchestrator/context_stitcher.py\nContextStitcher"]
        QL["engine/quota_ledger.py\nQuotaLedger"]
        LLM["orchestrator/llm_client.py\nLLMClient"]
    end

    subgraph ENRICH["Enrichment & IOC"]
        ES["engine/enrichment_scheduler.py\nEnrichmentScheduler"]
        IOCE["engine/ioc_extractor.py\nIOCExtractor"]
        VT[("VirusTotal / AbuseIPDB\nExternal APIs")]
    end

    subgraph WRITEBACK["TheHive Writeback"]
        WB["engine/writeback_thehive.py\nTheHiveWriteback"]
        TH[("TheHive Instance\n/api/v1/cases")]
    end

    subgraph MEMORY["Memory / RAG Layer"]
        RET["memory/retention.py\nRetentionManager"]
        EMB["memory/embeddings.py\nEmbeddingStore"]
        RAG["orchestrator/rag_retriever.py\nRAGRetriever"]
    end

    subgraph AUDIT["Hash Chain Audit Trail"]
        HC[("Hash Chain\n/var/lib/soc/audit/chain.jsonl")]
        SEAL["Seal Interval: 100 events\nor 5 minutes"]
    end

    WZ -->|tail -f / filebeat| IW
    IE -->|Suricata EVE JSON| KAFKA
    IW -->|normalize_to_alert()| KAFKA
    KAFKA -->|consume_batch()| SP
    SP -->|sanitize()| QUAR
    SP -->|seal_event()| HCS
    HCS -->|append_hash()| HC
    SP -->|enqueue()| QM
    QM -->|push_with_priority()| PQ
    PQ -->|backpressure_check()| BP
    BP -->|shed_if_overloaded()| SHED
    PQ -->|pop_next()| STW
    STW -->|get_model()| MR
    STW -->|stitch_context()| CS
    CS -->|retrieve()| RAG
    RAG -->|search()| EMB
    STW -->|check_quota()| QL
    STW -->|triage_alert()| ES
    ES -->|schedule_enrichment()| IOCE
    IOCE -->|extract_iocs()| VT
    STW -->|call_llm()| LLM
    LLM -->|multi-provider fallback| MR
    STW -->|write_case()| WB
    WB -->|create_case()| TH
    STW -->|update_retention()| RET
    RET -->|prune_expired()| EMB
```

### Key Data Structures

**Normalized Alert (engine/intake_wazuh.py:normalize_to_alert)**
```python
{
    "alert_id": "wazuh-20241219-001234",
    "timestamp": "2024-12-19T14:32:11.456Z",
    "source": "wazuh",
    "rule": {"id": "5715", "level": 12, "description": "SSH brute force"},
    "agent": {"id": "001", "name": "web-01", "ip": "10.0.1.15"},
    "data": {"srcip": "203.0.113.45", "dstport": 22, "attempts": 47},
    "raw": {...}
}
```

**Sanitized Alert (engine/sanitization_pipeline.py:sanitize)**
```python
{
    "alert_id": "wazuh-20241219-001234",
    "sanitized": True,
    "pii_redacted": ["user", "password", "email"],
    "iocs": [{"type": "ip", "value": "203.0.113.45"}],
    "hash_chain_prev": "a3f2...",
    "hash_chain_curr": "7b9e..."
}
```

---

## 2. Sanitization Pipeline & Quarantine Mechanism

```mermaid
flowchart TD
    subgraph INPUT["Raw Alert Input"]
        RAW[("Raw Alert\nJSON")]
    end

    subgraph PIPE["SanitizationPipeline (engine/sanitization_pipeline.py)"]
        VAL["validate_schema()\nPydantic AlertModel"]
        PII["redact_pii()\nRecursive dict traversal + Presidio"]
        IOC["extract_iocs()\nIOCExtractor"]
        NORM["normalize_fields()\nMITRE ATT&CK mapping"]
        SEAL["seal_event()\nHashChainSealer"]
    end

    subgraph QUARANTINE["Quarantine Store"]
        QFILE["/var/lib/soc/quarantine/\n{alert_id}.json.zst"]
        QIDX["/var/lib/soc/quarantine/index.sqlite"]
        QMETA["QuarantineMetadata\nreason, timestamp, original_hash"]
    end

    subgraph OUTPUT["Sanitized Output"]
        CLEAN[("Sanitized Alert\n+ hash_chain_prev/curr")]
        AUDIT[("Audit Entry\nHashChainSealer")]
    end

    RAW --> VAL
    VAL -->|valid| PII
    VAL -->|invalid| QUAR
    PII -->|pii_found| IOC
    PII -->|clean| IOC
    IOC --> NORM
    NORM --> SEAL
    SEAL --> CLEAN
    SEAL --> AUDIT
    QUAR --> QFILE
    QUAR --> QIDX
    QUAR --> QMETA
```

### SanitizationPipeline Class (engine/sanitization_pipeline.py)

```python
class SanitizationPipeline:
    def __init__(self, quarantine_dir: Path, hash_sealer: HashChainSealer):
        self.quarantine = QuarantineStore(quarantine_dir)
        self.sealer = hash_sealer
        self.analyzer = PresidioAnalyzer()
        self.ioc_extractor = IOCExtractor()

    def sanitize(self, raw_alert: dict) -> SanitizedAlert:
        alert = AlertModel(**raw_alert)
        redacted, pii_found = self._redact_pii(alert.model_dump())
        iocs = self.ioc_extractor.extract(redacted)
        normalized = self._normalize_fields(redacted, iocs)
        prev_hash = self.sealer.get_latest_hash()
        curr_hash = self.sealer.seal(normalized)
        normalized["hash_chain_prev"] = prev_hash
        normalized["hash_chain_curr"] = curr_hash
        return SanitizedAlert(**normalized)

    def _redact_pii(self, data: dict) -> tuple[dict, list[str]]:
        found = []
        def _traverse(obj: Any, path: str = "") -> Any:
            if isinstance(obj, dict):
                return {k: _traverse(v, f"{path}.{k}") for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_traverse(v, f"{path}[{i}]") for i, v in enumerate(obj)]
            elif isinstance(obj, str):
                results = self.analyzer.analyze(text=obj, entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IP_ADDRESS"], language="en")
                redacted_text = obj
                for result in sorted(results, key=lambda r: r.start, reverse=True):
                    found.append(f"{path}:{result.entity_type}")
                    redacted_text = redacted_text[:result.start] + "[REDACTED]" + redacted_text[result.end:]
                return redacted_text
            return obj
        return _traverse(data), found
```

### QuarantineStore (engine/sanitization_pipeline.py:QuarantineStore)

```python
class QuarantineStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index = sqlite3.connect(base_dir / "index.sqlite")
        self.index.execute("PRAGMA journal_mode=WAL")
        self._init_index()

    def _init_index(self):
        self.index.execute("""
            CREATE TABLE IF NOT EXISTS quarantine (
                alert_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                reason TEXT NOT NULL,
                original_hash TEXT NOT NULL,
                path TEXT NOT NULL
            )
        """)
        self.index.commit()

    def quarantine(self, alert_id: str, raw: dict, reason: str) -> Path:
        timestamp = datetime.utcnow().isoformat()
        original_hash = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        compressed = zstd.compress(json.dumps(raw, sort_keys=True).encode())
        qfile = self.base_dir / f"{alert_id}.json.zst"
        tmp_file = self.base_dir / f".{alert_id}.tmp"
        tmp_file.write_bytes(compressed)
        tmp_file.replace(qfile)
        self.index.execute(
            "INSERT OR REPLACE INTO quarantine VALUES (?, ?, ?, ?, ?)",
            (alert_id, timestamp, reason, original_hash, str(qfile))
        )
        self.index.commit()
        return qfile

    def retrieve(self, alert_id: str) -> dict | None:
        row = self.index.execute(
            "SELECT path FROM quarantine WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        if row:
            return json.loads(zstd.decompress(Path(row[0]).read_bytes()))
        return None
```

---

## 3. Triage Queue with Backpressure & Load Shedding

```mermaid
flowchart TD
    subgraph QUEUE_MGR["QueueManager (engine/queue_manager.py)"]
        ENQ["enqueue(alert, priority)"]
        DEQ["dequeue(worker_id)"]
        PRI["Priority Levels\nCRITICAL=0, HIGH=1, MEDIUM=2, LOW=3"]
        TTL["TTL per Priority\nCRITICAL: 4h, HIGH: 8h, MEDIUM: 24h, LOW: 72h"]
        TRIM["Explicit XTRIM\non backpressure"]
    end

    subgraph REDIS["Redis Streams"]
        STREAM["Stream: soc:triage:queue\nConsumer Group: triage-workers"]
        PENDING["Pending Entries List (PEL)"]
        CLAIMED["Claimed Entries"]
    end

    subgraph BACKPRESSURE["Backpressure Controller"]
        MON["monitor_queue_depth()\ninterval: 10s"]
        THRESH["Thresholds\nwarn: 1000, critical: 5000, max: 10000"]
        SIGNAL["emit_backpressure_signal()"]
    end

    subgraph SHEDDING["Load Shedder"]
        STRAT["Shedding Strategies"]
        DROP_LOW["drop_low_priority()\nTTL expired + LOW priority"]
        SAMPLE["sample_high_volume()\n10% of MEDIUM when > critical"]
        REJECT["reject_new_intake()\nreturn 429 to intake clients"]
    end

    subgraph WORKERS["SLMTriageWorker Pool"]
        W1["Worker-1\nconcurrency: 3"]
        W2["Worker-2\nconcurrency: 3"]
        WN["Worker-N\nconcurrency: 3"]
    end

    ENQ -->|XADD| STREAM
    STREAM -->|XREADGROUP| DEQ
    DEQ -->|XCLAIM| CLAIMED
    MON -->|XLEN| STREAM
    MON -->|check| THRESH
    THRESH -->|exceeded| SIGNAL
    SIGNAL --> STRAT
    STRAT --> DROP_LOW
    STRAT --> SAMPLE
    STRAT --> REJECT
    STRAT --> TRIM
    TRIM -->|XTRIM MAXLEN 10000| STREAM
    STREAM -->|XREADGROUP| W1
    STREAM -->|XREADGROUP| W2
    STREAM -->|XREADGROUP| WN
```

### QueueManager Implementation (engine/queue_manager.py)

```python
class QueueManager:
    PRIORITY_MAP = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    TTL_MAP = {"CRITICAL": 14400, "HIGH": 28800, "MEDIUM": 86400, "LOW": 259200}
    BACKPRESSURE_THRESHOLDS = {"warn": 1000, "critical": 5000, "max": 10000}
    MAX_STREAM_LENGTH = 10000

    def __init__(self, redis_client: redis.Redis, stream_key: str = "soc:triage:queue"):
        self.redis = redis_client
        self.stream_key = stream_key
        self.consumer_group = "triage-workers"
        self._ensure_group()

    def _ensure_group(self):
        try:
            self.redis.xgroup_create(self.stream_key, self.consumer_group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def enqueue(self, alert: SanitizedAlert, priority: str = "MEDIUM") -> str:
        priority_val = self.PRIORITY_MAP.get(priority, 2)
        ttl = self.TTL_MAP.get(priority, 86400)
        entry = {
            "alert_id": alert.alert_id,
            "payload": json.dumps(alert.model_dump(), sort_keys=True),
            "priority": str(priority_val),
            "enqueued_at": datetime.utcnow().isoformat(),
            "ttl": str(ttl),
            "attempts": "0"
        }
        msg_id = self.redis.xadd(self.stream_key, entry)
        return msg_id

    def dequeue(self, worker_id: str, count: int = 10, block_ms: int = 5000) -> list[QueuedAlert]:
        claimed = self._claim_pending(worker_id, count)
        if claimed:
            return claimed
        streams = {self.stream_key: ">"}
        results = self.redis.xreadgroup(self.consumer_group, worker_id, streams, count, block_ms)
        return [self._parse_entry(msg_id, data) for _, msgs in results for msg_id, data in msgs]

    def monitor_backpressure(self) -> BackpressureStatus:
        length = self.redis.xlen(self.stream_key)
        if length >= self.BACKPRESSURE_THRESHOLDS["max"]:
            return BackpressureStatus.MAX_EXCEEDED
        elif length >= self.BACKPRESSURE_THRESHOLDS["critical"]:
            return BackpressureStatus.CRITICAL
        elif length >= self.BACKPRESSURE_THRESHOLDS["warn"]:
            return BackpressureStatus.WARN
        return BackpressureStatus.NORMAL

    def shed_load(self, status: BackpressureStatus) -> ShedResult:
        if status == BackpressureStatus.MAX_EXCEEDED:
            self.redis.xtrim(self.stream_key, maxlen=self.MAX_STREAM_LENGTH, approximate=False)
            dropped = self._drop_expired_priority("LOW")
            sampled = self._sample_priority("MEDIUM", 0.1)
            return ShedResult(dropped=dropped, sampled=sampled, rejected_new=True)
        elif status == BackpressureStatus.CRITICAL:
            dropped = self._drop_expired_priority("LOW")
            return ShedResult(dropped=dropped, rejected_new=False)
        return ShedResult()

    def _drop_expired_priority(self, priority: str) -> int:
        priority_val = str(self.PRIORITY_MAP[priority])
        pass

    def _sample_priority(self, priority: str, rate: float) -> int:
        pass
```

---

## 4. Hash Chain Audit Trail

```mermaid
flowchart LR
    subgraph SEALER["HashChainSealer (engine/hash_chain_sealer.py)"]
        INIT["initialize_chain()\nGenesis: SHA256('LOCAL-SOC-SLM-v11.11')"]
        SEAL["seal_event(event)\nHMAC-SHA256(prev_hash || '|' || canonical_json)"]
        VERIFY["verify_chain(start, end)\nRecompute & compare"]
        ROTATE["rotate_key()\nHMAC-SHA256 with rotated key"]
    end

    subgraph STORAGE["Audit Storage"]
        CHAIN[("/var/lib/soc/audit/chain.jsonl\nOne line per sealed event")]
        MANIFEST[("/var/lib/soc/audit/manifest.json\nChain metadata + version")]
        SNAPSHOTS[("/var/lib/soc/audit/snapshots/\nHourly merkle roots")]
    end

    subgraph VERIFICATION["Verification Tools"]
        CLI["verify_chain.py\n--start N --end M"]
        AUDITOR["audit_report.py\nGenerates tamper-evidence report"]
    end

    INIT --> CHAIN
    SEAL --> CHAIN
    SEAL --> MANIFEST
    CHAIN --> SNAPSHOTS
    VERIFY --> CLI
    VERIFY --> AUDITOR
    ROTATE --> MANIFEST
```

### HashChainSealer (engine/hash_chain_sealer.py)

```python
class HashChainSealer:
    VERSION = 1
    DELIMITER = b"|"

    def __init__(self, chain_path: Path, key_rotation_interval: int = 86400):
        self.chain_path = chain_path
        self.chain_path.parent.mkdir(parents=True, exist_ok=True)
        self.current_key = self._load_or_generate_key()
        self.key_rotation_interval = key_rotation_interval
        self.last_rotation = time.time()
        self._lock = asyncio.Lock()
        self._latest_hash = self._get_latest_hash()
        self._seq = self._get_latest_sequence()

    def seal(self, event: dict) -> str:
        async with self._lock:
            canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
            message = self._latest_hash.encode() + self.DELIMITER + canonical.encode()
            hmac_digest = hmac.new(
                self.current_key,
                message,
                hashlib.sha256
            ).hexdigest()
            self._seq += 1
            entry = {
                "version": self.VERSION,
                "seq": self._seq,
                "timestamp": datetime.utcnow().isoformat(),
                "prev_hash": self._latest_hash,
                "curr_hash": hmac_digest,
                "event_hash": hashlib.sha256(canonical.encode()).hexdigest(),
                "key_id": self._get_key_id()
            }
            with open(self.chain_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
            self._latest_hash = hmac_digest
            self._maybe_rotate_key()
            return hmac_digest

    def verify_range(self, start_seq: int, end_seq: int) -> VerificationResult:
        mismatches = []
        expected_prev = "genesis" if start_seq == 1 else None
        with open(self.chain_path) as f:
            for line in f:
                entry = json.loads(line)
                if entry["seq"] < start_seq:
                    if entry["seq"] == start_seq - 1:
                        expected_prev = entry["curr_hash"]
                    continue
                if entry["seq"] > end_seq:
                    break
                if expected_prev is not None and entry["prev_hash"] != expected_prev:
                    mismatches.append({"seq": entry["seq"], "reason": "chain_break"})
                    continue
                expected = self._recompute_hash(entry, expected_prev)
                if expected != entry["curr_hash"]:
                    mismatches.append({"seq": entry["seq"], "reason": "hash_mismatch"})
                expected_prev = entry["curr_hash"]
        return VerificationResult(valid=len(mismatches)==0, mismatches=mismatches)

    def _maybe_rotate_key(self):
        if time.time() - self.last_rotation > self.key_rotation_interval:
            self.current_key = secrets.token_bytes(32)
            self.last_rotation = time.time()
            self._update_manifest({
                "key_rotation": self.last_rotation, 
                "key_id": self._get_key_id(),
                "seq_at_rotation": self._seq
            })
```

### Chain Entry Format (chain.jsonl)

```json
{"version": 1, "seq": 1, "timestamp": "2024-12-19T14:32:11.456Z", "prev_hash": "genesis", "curr_hash": "a3f2...", "event_hash": "7b9e...", "key_id": "key-1"}
{"version": 1, "seq": 2, "timestamp": "2024-12-19T14:32:15.123Z", "prev_hash": "a3f2...", "curr_hash": "4c8d...", "event_hash": "f1a2...", "key_id": "key-1"}
```

---

## 5. Memory / RAG Layer

```mermaid
flowchart TD
    subgraph EMBED["Embedding Store (memory/embeddings.py)"]
        MODEL["Embedding Model\nsentence-transformers/all-MiniLM-L6-v2"]
        INDEX["FAISS Index\nIndexFlatIP (cosine similarity)"]
        META["Metadata Store\nSQLite: alert_id, timestamp, tags"]
        UPSERT["upsert_embedding(alert_id, text, metadata)"]
        SEARCH["search(query, k=10, filter) -> list[ScoredResult]"]
        WAL["Write-Ahead Log\nembeddings.wal"]
    end

    subgraph RETENTION["Retention Manager (memory/retention.py)"]
        POLICY["RetentionPolicy\nCRITICAL: 2y, HIGH: 1y, MEDIUM: 180d, LOW: 90d"]
        PRUNE["prune_expired()\nDaily cron 03:00 UTC"]
        ARCHIVE["archive_to_cold()\nCompress + move to /cold"]
        STATS["retention_stats()\nCounts by tier"]
    end

    subgraph RAG["RAG Retriever (orchestrator/rag_retriever.py)"]
        QUERY["retrieve_context(alert, k=5)"]
        REWRITE["rewrite_query()\nExpand with MITRE tags"]
        RERANK["rerank_results()\nCross-encoder: ms-marco-MiniLM-L6-v2"]
        FORMAT["format_for_prompt()\n<context>...</context>"]
    end

    subgraph CONTEXT["Context Stitcher (orchestrator/context_stitcher.py)"]
        STITCH["stitch_context(alert, rag_results)"]
        TEMPLATE["Jinja2 Template\nsystem_prompt.j2"]
        INJECT["inject_iocs(), inject_history()"]
    end

    EMBED -->|store| RETENTION
    RETENTION -->|prune| EMBED
    RAG -->|search| EMBED
    RAG -->|rerank| MODEL
    CONTEXT -->|retrieve| RAG
    CONTEXT -->|render| TEMPLATE
    EMBED -.->|WAL sync| WAL
```

### EmbeddingStore (memory/embeddings.py)

```python
class EmbeddingStore:
    def __init__(self, index_path: Path, meta_db: Path, model_name: str = "all-MiniLM-L6-v2", wal_path: Path = None):
        self.model = SentenceTransformer(model_name)
        self.dimension = 384
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index_path = index_path
        self.meta_db = sqlite3.connect(meta_db)
        self.meta_db.execute("PRAGMA journal_mode=WAL")
        self._init_meta()
        self._load_index()
        self.wal_path = wal_path or index_path.with_suffix(".wal")
        self.wal_buffer = []
        self.wal_flush_interval = 10

    def _init_meta(self):
        self.meta_db.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                faiss_id INTEGER PRIMARY KEY,
                alert_id TEXT UNIQUE NOT NULL,
                metadata TEXT NOT NULL,
                created_at TEXT NOT NULL,
                text_preview TEXT
            )
        """)
        self.meta_db.commit()

    def upsert(self, alert_id: str, text: str, metadata: dict) -> None:
        embedding = self.model.encode([text], normalize_embeddings=True)[0]
        faiss_id = self.index.ntotal
        self.index.add(np.array([embedding], dtype=np.float32))
        self.meta_db.execute(
            "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?)",
            (faiss_id, alert_id, json.dumps(metadata), datetime.utcnow().isoformat(), text[:500])
        )
        self.meta_db.commit()
        self.wal_buffer.append({
            "op": "upsert",
            "faiss_id": faiss_id,
            "alert_id": alert_id,
            "embedding": embedding.tolist(),
            "metadata": metadata
        })
        if len(self.wal_buffer) >= self.wal_flush_interval:
            self.persist()

    def persist(self) -> None:
        faiss.write_index(self.index, str(self.index_path))
        if self.wal_buffer:
            with open(self.wal_path, "a") as f:
                for entry in self.wal_buffer:
                    f.write(json.dumps(entry) + "\n")
            self.wal_buffer.clear()

    def search(self, query: str, k: int = 10, filter_tags: list[str] = None) -> list[ScoredResult]:
        query_emb = self.model.encode([query], normalize_embeddings=True)[0]
        scores, indices = self.index.search(np.array([query_emb], dtype=np.float32), k * 3)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            row = self.meta_db.execute(
                "SELECT alert_id, metadata, text_preview FROM embeddings WHERE faiss_id = ?", (int(idx),)
            ).fetchone()
            if row and (not filter_tags or any(tag in json.loads(row[1]).get("tags", []) for tag in filter_tags)):
                results.append(ScoredResult(alert_id=row[0], score=float(score), metadata=json.loads(row[1]), preview=row[2]))
                if len(results) >= k:
                    break
        return results

    def prune_expired(self, retention_policy: RetentionPolicy) -> int:
        cutoff = datetime.utcnow() - timedelta(days=retention_policy.max_days)
        expired = self.meta_db.execute(
            "SELECT faiss_id FROM embeddings WHERE created_at < ?", (cutoff.isoformat(),)
        ).fetchall()
        if expired:
            keep_ids = set(range(self.index.ntotal)) - {row[0] for row in expired}
            self._rebuild_index(keep_ids)
            self.meta_db.execute("DELETE FROM embeddings WHERE created_at < ?", (cutoff.isoformat(),))
            self.meta_db.commit()
            self.persist()
        return len(expired)

    def _rebuild_index(self, keep_ids: set[int]):
        all_vectors = faiss.vector_to_array(self.index).reshape(self.index.ntotal, self.dimension)
        kept_vectors = all_vectors[list(sorted(keep_ids))]
        self.index = faiss.IndexFlatIP(self.dimension)
        if len(kept_vectors) > 0:
            self.index.add(kept_vectors)
```

### RAGRetriever (orchestrator/rag_retriever.py)

```python
class RAGRetriever:
    def __init__(self, embedding_store: EmbeddingStore, reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"):
        self.store = embedding_store
        self.reranker = CrossEncoder(reranker_model)

    def retrieve_context(self, alert: SanitizedAlert, k: int = 5) -> list[ContextChunk]:
        query_parts = [
            alert.rule.get("description", ""),
            " ".join([ioc["value"] for ioc in alert.iocs]),
            alert.agent.get("name", ""),
            " ".join(alert.mitre_tags or [])
        ]
        query = " ".join(filter(None, query_parts))
        expanded = self._expand_query(query, alert.mitre_tags)
        candidates = self.store.search(expanded, k=k*3, filter_tags=alert.mitre_tags)
        if not candidates:
            return []
        pairs = [(expanded, c.preview) for c in candidates]
        rerank_scores = self.reranker.predict(pairs)
        for c, score in zip(candidates, rerank_scores):
            c.rerank_score = float(score)
        candidates.sort(key=lambda x: x.rerank_score, reverse=True)
        return [ContextChunk(
            alert_id=c.alert_id,
            text=c.preview,
            metadata=c.metadata,
            relevance=c.rerank_score
        ) for c in candidates[:k]]

    def format_for_prompt(self, chunks: list[ContextChunk]) -> str:
        if not chunks:
            return "<context>No relevant historical cases found.</context>"
        parts = ["<context>"]
        for i, chunk in enumerate(chunks, 1):
            parts.append(f"  <case id=\"{chunk.alert_id}\" relevance=\"{chunk.relevance:.3f}\">")
            parts.append(f"    <summary>{chunk.text}</summary>")
            parts.append(f"    <tags>{', '.join(chunk.metadata.get('tags', []))}</tags>")
            parts.append(f"    <outcome>{chunk.metadata.get('outcome', 'unknown')}</outcome>")
            parts.append(f"  </case>")
        parts.append("</context>")
        return "\n".join(parts)
```

---

## 6. Overnight Self-Improving Pipeline (v11.11)

```mermaid
flowchart TD
    subgraph SCHEDULER["Overnight Scheduler\ncron: 0 2 * * *"]
        TRIGGER["Trigger: 02:00 UTC daily"]
    end

    subgraph SELF_IMPROVER["overnight/self_improver.py\nSelfImprover"]
        ANALYZE["analyze_false_positives()\nQuery TheHive for closed FP cases"]
        MINE["mine_patterns()\nCluster similar alerts\nDBSCAN on embeddings"]
        GENERATE["generate_rules()\nYARA / Sigma rule candidates"]
        VALIDATE["validate_rules()\nBacktest against 30d history"]
        PROPOSE["propose_prompt_updates()\nDiff against current prompts"]
        COMMIT["commit_changes()\nWrite to fix_backlog.json"]
    end

    subgraph LLM_CLIENT["orchestrator/llm_client.py\nLLMClient"]
        PROVIDERS["Multi-Provider Fallback\n1. Ollama (local)\n2. OpenRouter\n3. LM Studio\n4. vLLM"]
        RATE_LIMIT["RateLimitManager\nToken bucket per provider"]
        CIRCUIT["Circuit Breaker\nOpen after 5 failures"]
        RETRY["Exponential Backoff\nmax_retries=3, base=2s"]
        TASKGROUP["asyncio.TaskGroup\nParallel provider attempts"]
    end

    subgraph QUOTA["openrouter_quota.py\nOpenRouterQuotaManager"]
        CHECK["check_quota()\nDaily limit tracking"]
        RESERVE["reserve_tokens()\nPre-allocate for overnight run"]
        REFILL["refill_at_midnight()\nUTC reset"]
        BACKLOG["fix_backlog.json\nDeferred improvements"]
    end

    TRIGGER --> ANALYZE
    ANALYZE --> MINE
    MINE --> GENERATE
    GENERATE --> VALIDATE
    VALIDATE --> PROPOSE
    PROPOSE --> COMMIT
    VALIDATE -->|Uses for rule generation| LLM_CLIENT
    LLM_CLIENT -->|Managed by| QUOTA
    QUOTA -->|Updates| BACKLOG
    BACKLOG -->|Next run| ANALYZE
```

### SelfImprover (overnight/self_improver.py)

```python
class SelfImprover:
    def __init__(
        self,
        hive_client: TheHiveClient,
        embedding_store: EmbeddingStore,
        llm_client: LLMClient,
        quota_manager: OpenRouterQuotaManager,
        backlog_path: Path = Path("/var/lib/soc/fix_backlog.json")
    ):
        self.hive = hive_client
        self.embeddings = embedding_store
        self.llm = llm_client
        self.quota = quota_manager
        self.backlog_path = backlog_path
        self.backlog = self._load_backlog()

    async def run(self) -> ImprovementReport:
        if not await self.quota.reserve_tokens(estimated=50000):
            logger.warning("Insufficient OpenRouter quota, deferring to backlog")
            return ImprovementReport


---

# Operations Runbook

*Source: `docs/OPERATIONS_RUNBOOK.md` (711 lines)*

# LOCAL-SOC-SLM Operations Runbook

## Version: 11.9
## Last Updated: 2025-01-15

---

## 1. Starting/Stopping Services

### 1.1 Start All Core Services

```bash
# Activate virtual environment first
source /opt/local-soc-slm/venv/bin/activate

# Start the intake layer (Wazuh + Eve)
cd /opt/local-soc-slm
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
pkill -9 -f "/opt/local-soc-slm/venv/bin/python"
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
# Ensure soc-user has write access to /var/log/local-soc-slm/ and read access to /opt/local-soc-slm/venv/
# Add to /etc/cron.d/local-soc-slm:
# 0 2 * * * soc-user /opt/local-soc-slm/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml >> /var/log/local-soc-slm/self_improver.log 2>&1

# Manual execution for testing (use absolute venv python path)
cd /opt/local-soc-slm
/opt/local-soc-slm/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --dry-run

# Full run with backlog processing (backlog stored in /data/ for consistency with state files)
/opt/local-soc-slm/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --process-backlog /data/self_improver/fix_backlog.json
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
tail -100 /var/log/local-soc-slm/hash_chain_sealer.log | grep -i error

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
grep -i "enrichment failed" /var/log/local-soc-slm/enrichment_scheduler.log | tail -20

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
journalctl -u local-soc-slm --since "1 hour ago" | grep -i "oom\|killed\|segfault"

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
/opt/local-soc-slm/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --dry-run --verbose

# Full run with specific date
/opt/local-soc-slm/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --date 2025-01-14

# Process accumulated backlog (stored in /data/ for consistency)
/opt/local-soc-slm/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --process-backlog /data/self_improver/fix_backlog.json --max-items 500

# Force re-evaluation of specific model
/opt/local-soc-slm/venv/bin/python -m overnight.self_improver --config config/self_improver.yaml --reevaluate-model llama-3.1-8b
```

### 7.3 Monitor Pipeline Execution

```bash
# Check last run status
cat /var/log/local-soc-slm/self_improver/latest_run.json | jq .

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
cat /var/log/local-soc-slm/self_improver/latest_run.json | jq '.error'

# Common failures and fixes:

# 1. Quota exhausted
# Check: python -m engine.openrouter_quota --status
# Fix: Wait for reset or rotate key (Section 6.1)

# 2. All LLM providers failed
# Check: grep "fallback exhausted" /var/log/local-soc-slm/self_improver.log
# Fix: Verify llm_providers.yaml, check network connectivity

# 3. Backlog corruption
# Check: python -m overnight.self_improver --validate-backlog /data/self_improver/fix_backlog.json
# Fix: python -m overnight.self_improver --repair-backlog /data/self_improver/fix_backlog.json

# 4. Prompt optimization failed validation
# Check: grep "validation failed" /var/log/local-soc-slm/self_improver.log
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
| Intake Wazuh | `config/intake_wazuh.yaml` | `/var/log/local-soc-slm/intake_wazuh.log` | `/data/queue/intake_raw` |
| Intake Eve | `config/intake_eve.yaml` | `/var/log/local-soc-slm/intake_eve.log` | `/data/queue/intake_raw` |
| Sanitization | `config/sanitization.yaml` | `/var/log/local-soc-slm/sanitization.log` | `/data/queue/sanitization` |
| Queue Manager | `config/queue.yaml` | `/var/log/local-soc-slm/queue_manager.log` | `/data/queue/*` |
| SLM Triage | `config/slm_triage_worker.yaml` | `/var/log/local-soc-slm/slm_triage.log` | `/data/queue/triage_pending` |
| Enrichment | `config/enrichment.yaml` | `/var/log/local-soc-slm/enrichment.log` | `/data/queue/enrichment_pending` |
| Hash Chain | `config/hash_chain.yaml` | `/var/log/local-soc-slm/hash_chain_sealer.log` | `/data/hash_chain/` |
| Model Registry | `config/model_registry.yaml` | `/var/log/local-soc-slm/model_registry.log` | `/data/models/` |
| LLM Providers | `config/llm_providers.yaml` | `/var/log/local-soc-slm/llm_client.log` | - |
| Self Improver | `config/self_improver.yaml` | `/var/log/local-soc-slm/self_improver.log` | `/data/self_improver/` |
| OpenRouter Quota | `config/openrouter_quota.yaml` | `/var/log/local-soc-slm/openrouter_quota.log` | `/data/quota/openrouter.json` |
| Fix Backlog | - | - | `/data/self_improver/fix_backlog.json` |
| Retention | `config/retention.yaml` | `/var/log/local-soc-slm/retention.log` | `/data/memory/` |
| Embeddings | `config/embeddings.yaml` | `/var/log/local-soc-slm/embeddings.log` | `/data/embeddings/` |

---

## 10. Useful One-Liners

```bash
# Quick health check
python -m engine.queue_manager --status --json | jq -r '.overall_health'

# Tail all logs
tail -f /var/log/local-soc-slm/*.log

# Count messages processed last hour
grep "processed" /var/log/local-soc-slm/slm_triage.log | grep "$(date -d '1 hour ago' '+%H:')" | wc -l

# Check GPU utilization
watch -n 5 nvidia-smi

# Check disk space for queues
df -h /data/queue

# Verify all daemons running
pgrep -af "python -m engine\.|python -m orchestrator\.|python -m memory\." | wc -l
```

---

*End of Runbook*


---

# Deployment Runbook

*Source: `docs/deployment_runbook.md` (713 lines)*

# LOCAL-SOC-SLM Deployment Runbook v11.11

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


---

# Lab Setup Guide

*Source: `docs/LAB_SETUP_GUIDE.md` (837 lines)*

# LOCAL-SOC-SLM Lab Setup Guide v11.11

## 1. Hardware Requirements

### Minimum Specifications
| Component | Specification | Notes |
|-----------|---------------|-------|
| **CPU** | 8 cores (x86_64, AVX2 support) | 16 cores recommended for concurrent LLM inference |
| **RAM** | 32 GB DDR4/DDR5 | 64 GB for full stack + model caching |
| **Storage** | 500 GB NVMe SSD | 1 TB+ for Wazuh indices + PostgreSQL + model weights |
| **GPU** | Optional: NVIDIA 12 GB VRAM | For local LLM acceleration (llama.cpp, vLLM) |
| **Network** | 1 Gbps dedicated | Isolated management VLAN recommended |

### Recommended Production Specs
- **CPU**: AMD EPYC / Intel Xeon 16+ cores
- **RAM**: 128 GB ECC
- **Storage**: 2 TB NVMe (ZFS mirror) + 4 TB HDD for cold retention
- **GPU**: 2× NVIDIA RTX 4090 / A6000 for model parallelism

---

## 2. Docker Compose Stack

### 2.1 Complete `docker-compose.yml`

```yaml
version: '3.8'

services:
  # --- Core Infrastructure ---
  postgres:
    image: pgvector/pgvector:pg16
    container_name: local-soc-postgres
    environment:
      POSTGRES_DB: soc_memory
      POSTGRES_USER: soc_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_INITDB_ARGS: "--auth-host=scram-sha-256"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./sql/init_pgvector.sql:/docker-entrypoint-initdb.d/init_pgvector.sql:ro
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U soc_user -d soc_memory"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - soc_internal

  redis:
    image: redis:7-alpine
    container_name: local-soc-redis
    command: redis-server --appendonly yes --maxmemory 2gb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    networks:
      - soc_internal

  # --- Wazuh Stack ---
  wazuh-indexer:
    image: wazuh/wazuh-indexer:4.7.0
    container_name: wazuh-indexer
    environment:
      - OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g
      - discovery.type=single-node
    volumes:
      - wazuh_indexer_data:/var/lib/wazuh-indexer
      - ./certs:/certs:ro
    ports:
      - "9200:9200"
      - "9300:9300"
    ulimits:
      memlock:
        soft: -1
        hard: -1
      nofile:
        soft: 65536
        hard: 65536
    networks:
      - soc_internal

  wazuh-indexer-init:
    image: wazuh/wazuh-indexer:4.7.0
    container_name: wazuh-indexer-init
    entrypoint: ["/bin/bash", "-c"]
    command:
      - |
        /usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh \
          -cd /usr/share/wazuh-indexer/plugins/opensearch-security/securityconfig/ \
          -icl -nhnv \
          -cacert /certs/root-ca.pem \
          -cert /certs/admin.pem \
          -key /certs/admin.key \
          -h wazuh-indexer
    volumes:
      - ./certs:/certs:ro
    depends_on:
      wazuh-indexer:
        condition: service_started
    networks:
      - soc_internal

  wazuh-manager:
    image: wazuh/wazuh-manager:4.7.0
    container_name: wazuh-manager
    environment:
      - INDEXER_URL=https://wazuh-indexer:9200
      - INDEXER_USERNAME=admin
      - INDEXER_PASSWORD=${WAZUH_INDEXER_PASSWORD}
      - API_USERNAME=wazuh-api
      - API_PASSWORD=${WAZUH_API_PASSWORD}
      - FILEBEAT_SSL_VERIFICATION_MODE=none
    volumes:
      - wazuh_manager_data:/var/ossec/data
      - wazuh_logs:/var/ossec/logs
      - ./certs:/certs:ro
      - ./config/wazuh/ossec.conf:/wazuh-config-mount/ossec.conf:ro
    ports:
      - "1514:1514/udp"
      - "1515:1515"
      - "55000:55000"
    depends_on:
      wazuh-indexer:
        condition: service_healthy
      wazuh-indexer-init:
        condition: service_completed_successfully
    networks:
      - soc_internal
      - soc_external

  wazuh-dashboard:
    image: wazuh/wazuh-dashboard:4.7.0
    container_name: wazuh-dashboard
    environment:
      - INDEXER_URL=https://wazuh-indexer:9200
      - INDEXER_USERNAME=admin
      - INDEXER_PASSWORD=${WAZUH_INDEXER_PASSWORD}
      - DASHBOARD_PASSWORD=${WAZUH_DASHBOARD_PASSWORD}
    ports:
      - "5601:5601"
    depends_on:
      - wazuh-indexer
    networks:
      - soc_internal
      - soc_external

  # --- Suricata IDS ---
  suricata:
    image: jasonish/suricata:latest
    container_name: local-soc-suricata
    cap_add:
      - NET_ADMIN
      - NET_RAW
      - SYS_NICE
    network_mode: host
    volumes:
      - ./config/suricata/suricata.yaml:/etc/suricata/suricata.yaml:ro
      - ./config/suricata/rules:/etc/suricata/rules:ro
      - suricata_logs:/var/log/suricata
      - ./pcap:/pcap:ro
      - suricata_socket:/var/run/suricata
    command: -i eth0 -c /etc/suricata/suricata.yaml --set outputs.1.eve-log.enabled=yes --set outputs.1.eve-log.filetype=unix_stream --set outputs.1.eve-log.filename=/var/run/suricata/eve.sock
    healthcheck:
      test: ["CMD", "suricata", "--build-info"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - soc_external

  # --- TheHive Case Management ---
  thehive:
    image: strangebee/thehive:5.2.7
    container_name: local-soc-thehive
    environment:
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=thehive
      - DB_USER=soc_user
      - DB_PASSWORD=${POSTGRES_PASSWORD}
      - APPLICATION_SECRET=${THEHIVE_APP_SECRET}
      - CORTEX_URL=http://cortex:9001
    volumes:
      - thehive_data:/opt/thp/thehive/data
      - thehive_logs:/opt/thp/thehive/logs
    ports:
      - "9000:9000"
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - soc_internal
      - soc_external

  cortex:
    image: strangebee/cortex:3.1.8
    container_name: local-soc-cortex
    environment:
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=cortex
      - DB_USER=soc_user
      - DB_PASSWORD=${POSTGRES_PASSWORD}
      - APPLICATION_SECRET=${CORTEX_APP_SECRET}
      - JOB_DIRECTORY=/opt/cortex/jobs
    volumes:
      - cortex_data:/opt/cortex/data
      - cortex_logs:/opt/cortex/logs
    ports:
      - "9001:9001"
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - soc_internal

  # --- LOCAL-SOC-SLM Engine ---
  slm-engine:
    build:
      context: ..
      dockerfile: docker/engine.Dockerfile
    container_name: local-soc-slm-engine
    user: "1000:1000"
    environment:
      - POSTGRES_DSN=postgresql://soc_user:${POSTGRES_PASSWORD}@postgres:5432/soc_memory
      - REDIS_URL=redis://redis:6379/0
      - WAZUH_API_URL=https://wazuh-manager:55000
      - WAZUH_API_USER=wazuh-api
      - WAZUH_API_PASSWORD=${WAZUH_API_PASSWORD}
      - SURICATA_EVE_SOCK=/var/run/suricata/eve.sock
      - THEHIVE_URL=http://thehive:9000
      - THEHIVE_API_KEY=${THEHIVE_API_KEY}
      - MODEL_REGISTRY_PATH=/models/registry.json
      - EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
      - LOG_LEVEL=INFO
      - QUOTA_LEDGER_PATH=/data/quota_ledger.json
      - FIX_BACKLOG_PATH=/data/fix_backlog.json
      - OPENROUTER_QUOTA_PATH=/data/openrouter_quota.json
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
    volumes:
      - ../engine:/app/engine:ro
      - ../orchestrator:/app/orchestrator:ro
      - ../memory:/app/memory:ro
      - ../overnight:/app/overnight:ro
      - ./models:/models:ro
      - slm_engine_data:/data
      - ./data/fix_backlog.json:/data/fix_backlog.json
      - ./data/openrouter_quota.json:/data/openrouter_quota.json
      - suricata_socket:/var/run/suricata:ro
      - ./config/engine:/config:ro
    ports:
      - "8080:8080"
      - "9090:9090"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      wazuh-manager:
        condition: service_started
      suricata:
        condition: service_healthy
      thehive:
        condition: service_started
    networks:
      - soc_internal
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          memory: 4G

  # --- Overnight Self-Improving Pipeline (v11.11) ---
  slm-overnight:
    build:
      context: ..
      dockerfile: docker/overnight.Dockerfile
    container_name: local-soc-slm-overnight
    user: "1000:1000"
    environment:
      - POSTGRES_DSN=postgresql://soc_user:${POSTGRES_PASSWORD}@postgres:5432/soc_memory
      - REDIS_URL=redis://redis:6379/0
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - OPENROUTER_QUOTA_PATH=/data/openrouter_quota.json
      - FIX_BACKLOG_PATH=/data/fix_backlog.json
      - MODEL_REGISTRY_PATH=/models/registry.json
      - EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
      - SELF_IMPROVER_SCHEDULE=0 3 * * *
      - LOG_LEVEL=INFO
    volumes:
      - ../overnight:/app/overnight:ro
      - ../engine:/app/engine:ro
      - ../orchestrator:/app/orchestrator:ro
      - ../memory:/app/memory:ro
      - ./models:/models:ro
      - slm_overnight_data:/data
      - ./data/fix_backlog.json:/data/fix_backlog.json
      - ./data/openrouter_quota.json:/data/openrouter_quota.json
      - ./config/overnight:/config:ro
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      slm-engine:
        condition: service_started
    networks:
      - soc_internal
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G

  # --- Prometheus + Grafana Monitoring ---
  prometheus:
    image: prom/prometheus:v2.48.0
    container_name: local-soc-prometheus
    volumes:
      - ./config/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    ports:
      - "9091:9090"
    networks:
      - soc_internal

  grafana:
    image: grafana/grafana:10.2.0
    container_name: local-soc-grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
    volumes:
      - grafana_data:/var/lib/grafana
      - ./config/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./config/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
    networks:
      - soc_internal
      - soc_external

volumes:
  postgres_data:
  redis_data:
  wazuh_indexer_data:
  wazuh_manager_data:
  wazuh_logs:
  suricata_logs:
  suricata_socket:
  thehive_data:
  thehive_logs:
  cortex_data:
  cortex_logs:
  slm_engine_data:
  slm_overnight_data:
  prometheus_data:
  grafana_data:

networks:
  soc_internal:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
  soc_external:
    driver: bridge
    ipam:
      config:
        - subnet: 172.29.0.0/16
```

### 2.2 Engine Dockerfile (`docker/engine.Dockerfile`)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for socket access
RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -m appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine/ ./engine/
COPY orchestrator/ ./orchestrator/
COPY memory/ ./memory/
COPY overnight/ ./overnight/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080 9090

USER appuser

CMD ["python", "-m", "engine.queue_manager"]
```

### 2.3 Overnight Dockerfile (`docker/overnight.Dockerfile`)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for shared volume access
RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -m appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY overnight/ ./overnight/
COPY engine/ ./engine/
COPY orchestrator/ ./orchestrator/
COPY memory/ ./memory/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Install cron job for self-improver running as appuser
RUN echo "0 3 * * * /usr/local/bin/python -m overnight.self_improver >> /var/log/self_improver.log 2>&1" > /etc/cron.d/self-improver \
    && chmod 0644 /etc/cron.d/self-improver \
    && crontab -u appuser /etc/cron.d/self-improver

# Create log file and set permissions
RUN touch /var/log/self_improver.log && chown appuser:appuser /var/log/self_improver.log

USER appuser

CMD ["cron", "-f", "-L", "15"]
```

### 2.4 Requirements (`requirements.txt`)

```text
# Core dependencies
fastapi==0.109.0
uvicorn[standard]==0.27.0
pydantic==2.5.3
pydantic-settings==2.1.0
tenacity==8.2.3

# Database
asyncpg==0.29.0
sqlalchemy[asyncio]==2.0.25
alembic==1.13.1
psycopg2-binary==2.9.9
pgvector==0.2.3

# Redis & Queue
redis==5.0.1
rq==1.15.1

# HTTP Clients
httpx==0.26.0
aiohttp==3.9.1

# Wazuh / Suricata
wazuh-py==0.0.4

# ML / Embeddings
sentence-transformers==2.5.1
torch==2.2.0
transformers==4.37.2
accelerate==0.27.2

# Utilities
python-dotenv==1.0.0
pyyaml==6.0.1
orjson==3.9.10
xxhash==3.4.1
croniter==2.0.1

# Monitoring
prometheus-client==0.19.1
```

---

## 3. Network Topology and Port Mappings

### 3.1 Network Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL NETWORK (172.29.0.0/16)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  Wazuh       │  │  TheHive     │  │  Grafana     │  │  Suricata    │    │
│  │  Dashboard   │  │  (9000)      │  │  (3000)      │  │  (Host NIC)  │    │
│  │  :5601       │  │  Cortex:9001 │  │              │  │              │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                 │                 │                 │            │
└─────────┼─────────────────┼─────────────────┼─────────────────┼────────────┘
          │                 │                 │                 │
          ▼                 ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INTERNAL NETWORK (172.28.0.0/16)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  Wazuh       │  │  PostgreSQL  │  │  Redis       │  │  SLM Engine  │    │
│  │  Manager     │  │  + pgvector  │  │  (6379)      │  │  (8080/9090) │    │
│  │  :55000      │  │  :5432       │  │              │  │              │    │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘  └──────┬───────┘    │
│         │                 │                                    │            │
│         │                 │              ┌──────────────┐      │            │
│         │                 └──────────────│  SLM Overnight│──────┘            │
│         │                                │  (Cron 3 AM)  │                   │
│         │                                └──────────────┘                   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────┐                                                           │
│  │  Wazuh       │                                                           │
│  │  Indexer     │                                                           │
│  │  :9200/9300  │                                                           │
│  └──────────────┘                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Port Mapping Table

| Service | Internal Port | External Port | Protocol | Purpose |
|---------|---------------|---------------|----------|---------|
| Wazuh Manager API | 55000 | 55000 | HTTPS | Agent enrollment, alert query |
| Wazuh Agent | 1514 | 1514 | UDP | Syslog/agent logs |
| Wazuh Agent Enrollment | 1515 | 1515 | TCP | Agent registration |
| Wazuh Indexer | 9200 | 9200 | HTTPS | OpenSearch REST API |
| Wazuh Indexer Transport | 9300 | 9300 | TCP | Node-to-node |
| Wazuh Dashboard | 5601 | 5601 | HTTPS | Web UI |
| Suricata Eve Socket | Unix socket | N/A | Unix | JSON event stream to engine |
| TheHive | 9000 | 9000 | HTTP | Case management API |
| Cortex | 9001 | 9001 | HTTP | Analyzer/responder API |
| PostgreSQL + pgvector | 5432 | 5432 | TCP | Primary datastore |
| Redis | 6379 | 6379 | TCP | Queue, cache, rate-limit |
| SLM Engine API | 8080 | 8080 | HTTP | Internal REST API |
| SLM Engine Metrics | 9090 | 9090 | HTTP | Prometheus scrape |
| Prometheus | 9090 | 9091 | HTTP | Metrics collection |
| Grafana | 3000 | 3000 | HTTP | Visualization |

### 3.3 Firewall Rules (UFW Example)

```bash
# Management access (restrict to admin CIDR)
ufw allow from 10.0.0.0/8 to any port 22 proto tcp    # SSH
ufw allow from 10.0.0.0/8 to any port 5601 proto tcp  # Wazuh Dashboard
ufw allow from 10.0.0.0/8 to any port 9000 proto tcp  # TheHive
ufw allow from 10.0.0.0/8 to any port 3000 proto tcp  # Grafana
ufw allow from 10.0.0.0/8 to any port 9091 proto tcp  # Prometheus

# Sensor network (Suricata span/tap port - no firewall needed, host mode)

# Inter-container communication handled by Docker networks
```

### 3.4 Suricata Socket Permissions Setup

```bash
# Run once before docker-compose up to ensure socket accessibility
mkdir -p ./data
touch ./data/fix_backlog.json ./data/openrouter_quota.json
echo '{}' > ./data/fix_backlog.json
echo '{"daily_limit": 1000, "used": 0, "reset_date": "'$(date +%Y-%m-%d)'"}' > ./data/openrouter_quota.json
chmod 664 ./data/fix_backlog.json ./data/openrouter_quota.json

# Ensure suricata_socket volume has correct group for socket access
# The slm-engine user (UID 1000) must have read access to the unix socket
# Suricata creates the socket as root; set group ownership on host
sudo chown -R 1000:1000 ./data
```

---

## 4. Initial Configuration Steps

### 4.1 Prerequisites

```bash
# Clone repository
git clone https://github.com/your-org/LOCAL-SOC-SLM.git
cd LOCAL-SOC-SLM

# Create .env file from template
cp .env.example .env
# Edit .env with secure passwords (see section 4.2)

# Generate TLS certificates for Wazuh
mkdir -p certs
docker run --rm -v $(pwd)/certs:/certs wazuh/wazuh-certs-tool:4.7.0 \
  -a -n 3 -o /certs -x 3650

# Prepare persistent data files for v11.11 pipeline
mkdir -p ./data
touch ./data/fix_backlog.json ./data/openrouter_quota.json
echo '{}' > ./data/fix_backlog.json
echo '{"daily_limit": 1000, "used": 0, "reset_date": "'$(date +%Y-%m-%d)'"}' > ./data/openrouter_quota.json
chmod 664 ./data/fix_backlog.json ./data/openrouter_quota.json
```

### 4.2 Environment Variables (`.env`)

```bash
# Database
POSTGRES_PASSWORD=changeme_secure_postgres_password

# Wazuh
WAZUH_INDEXER_PASSWORD=changeme_wazuh_indexer_password
WAZUH_API_PASSWORD=changeme_wazuh_api_password
WAZUH_DASHBOARD_PASSWORD=changeme_wazuh_dashboard_password

# TheHive / Cortex
THEHIVE_APP_SECRET=$(openssl rand -base64 32)
CORTEX_APP_SECRET=$(openssl rand -base64 32)
THEHIVE_API_KEY=changeme_thehive_api_key

# OpenRouter (for overnight self-improver multi-provider fallback)
OPENROUTER_API_KEY=sk-or-v1-your-openrouter-key

# Grafana
GRAFANA_PASSWORD=changeme_grafana_password

# Optional Threat Intel
ABUSEIPDB_API_KEY=
VIRUSTOTAL_API_KEY=
OTX_API_KEY=
```

### 4.3 Suricata Configuration (`config/suricata/suricata.yaml`)

```yaml
%YAML 1.1
---
vars:
  address-groups:
    HOME_NET: "[192.168.0.0/16,10.0.0.0/8,172.16.0.0/12]"
    EXTERNAL_NET: "!$HOME_NET"
  port-groups:
    HTTP_PORTS: "80,8080,8000,8888"
    SHELLCODE_PORTS: "!80"

default-log-level: info
default-log-format: "[%i] %t - (%f:%l) <%d> (%n) -- "

outputs:
  - fast:
      enabled: yes
      filename: /var/log/suricata/fast.log
  - eve-log:
      enabled: yes
      filetype: unix_stream
      filename: /var/run/suricata/eve.sock
      types:
        - alert:
            payload: yes
            payload-buffer-size: 4kb
            payload-printable: yes
            packet: yes
            metadata: yes
            tagged-packets: yes
        - http:
            extended: yes
        - dns:
            query: yes
            answer: yes
        - tls:
            extended: yes
        - files:
            force-magic: no
            force-md5: no
        - ssh
        - smtp
        - flow

af-packet:
  - interface: eth0
    cluster-id: 99
    cluster-type: cluster_flow
    defrag: yes
    use-mmap: yes
    tpacket-v3: yes
    ring-size: 200000
    block-size: 1048576
    block-timeout: 10

rule-files:
  - suricata.rules
  - /etc/suricata/rules/*.rules

classification-file: /etc/suricata/classification.config
reference-config-file: /etc/suricata/reference.config

threshold-file: /etc/suricata/threshold.config

engine-analysis:
  rules-fast-pattern: yes
  rules: yes

unix-command:
  enabled: yes
  filename: /var/run/suricata/suricata-command.socket

legacy:
  uricontent: enabled

lua:
  enabled: yes
```

### 4.4 Wazuh Manager Configuration (`config/wazuh/ossec.conf`)

```xml
<ossec_config>
  <global>
    <jsonout_output>yes</jsonout_output>
    <alerts_log>yes</alerts_log>
    <logall>no</logall>
    <logall_json>no</logall_json>
    <email_notification>no</email_notification>
    <smtp_server>localhost</smtp_server>
    <email_from>wazuh@local-soc</email_from>
    <email_to>soc@local-soc</email_to>
    <email_maxperhour>12</email_maxperhour>
  </global>

  <alerts>
    <log_alert_level>3</log_alert_level>
    <email_alert_level>12</email_alert_level>
  </alerts>

  <api>
    <enabled>yes</enabled>
    <host>0.0.0.0</host>
    <port>55000</port>
    <max_threads>8</max_threads>
    <ssl>
      <enabled>yes</enabled>
      <key>/certs/wazuh-manager.key</key>
      <cert>/certs/wazuh-manager.pem</cert>
    </ssl>
    <auth>
      <enabled>yes</enabled>
      <port>1515</port>
      <ssl_agent_ca>/certs/root-ca.pem</ssl_agent_ca>
      <ssl_verify_host>no</ssl_verify_host>
      <ciphers>HIGH:!ADH:!EXP:!MD5:!RC4:!3DES:!CAMELLIA:@STRENGTH</ciphers>
    </auth>
  </api>

  <cluster>
    <name>local-soc-cluster</name>
    <node_name>wazuh-manager-01</node_name>
    <node_type>master</node_type>
    <key>changeme_cluster_key</key>
    <interval>2m</interval>
    <port>1516</port>
    <bind_addr>0.0.0.0</bind_addr>
    <nodes>
      <node>wazuh-manager</node>
    </nodes>
    <hidden>no</hidden>
    <disabled>no</disabled>
  </cluster>

  <indexer>
    <enabled>yes</enabled>
    <hosts>
      <host>https://wazuh-indexer:9200</host>
    </hosts>
    <username>admin</username>
    <password>${WAZUH_INDEXER_PASSWORD}</password>
    <ssl>
      <enabled>yes</enabled>
      <verify>no</verify>
    </ssl>
    <index_prefix>wazuh-alerts</index_prefix>
    <rollover>
      <enabled>yes</enabled>
      <max_age>30d</max_age>
      <max_size>50gb</max_size>
    </rollover>
  </indexer>

  <syscheck>
    <disabled>no</disabled>
    <frequency>43200</frequency>
    <scan_on_start>yes</scan_on_start>
    <directories check_all="yes">/etc,/usr/bin,/usr/sbin</directories>
    <directories check_all="yes">/bin,/sbin,/boot</directories>
    <ignore>/etc/mtab</ignore>
    <ignore>/etc/hosts.deny</ignore>
    <ignore>/etc/mail/statistics</ignore>
    <ignore>/etc/random-seed</ignore>
    <ignore>/etc/random.seed</ignore>
    <ignore>/etc/adjtime</ignore>
    <ignore>/etc/httpd/logs</ignore>
    <ignore>/etc/utmpx</ignore>
    <ignore>/etc/wtmpx</ignore>
    <ignore>/etc/cups/certs</ignore>
    <ignore>/etc/dumpdates</ignore>
    <ignore>/etc/svc/volatile</ignore>
    <nodiff>/etc/ssl/private.key</nodiff>
    <skip_nfs>yes</skip_nfs>
    <skip_dev>yes</skip_dev>
    <skip_proc>yes</skip_proc>
    <skip_sys>yes</skip_sys>
    <process_priority>10</process_priority>
    <max_eps>100</max_eps>
    <synchronization>
      <enabled>yes</enabled>
      <interval>5m</interval>
      <max_interval>1h</max_interval>
    </synchron


---

# Operator Manual

*Source: `docs/operator_manual.md` (589 lines)*

# LOCAL-SOC-SLM Operator Manual v11.11

## ⚠️ Breaking Changes (v11.11)

- **Removed**: `engine/intake_syslog.py` — Migrate to `intake_wazuh.py` or `intake_eve.py` immediately.
- **Schema Change**: `sanitization_pipeline.py` now requires `config/sanitization_rules.yaml` v2 schema (adds `pii_entity_types` field).
- **Hash Chain**: Seal interval reduced from 10k to 1k events for higher audit granularity.
- **New Dependency**: `liburing-dev` must be installed **before** building the Python environment (`apt install liburing-dev` then `pip install -r requirements.txt`).

---

## 1. System Overview

LOCAL-SOC-SLM is a local Security Operations Center automation platform designed for air-gapped and hybrid environments. The platform processes security events through a multi-layered pipeline:

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
**Classification**: INTERNAL - OPERATIONAL


---

# Overnight Pipeline (v11.11)

*Source: `docs/OVERNIGHT_PIPELINE.md` (493 lines)*

# OVERNIGHT PIPELINE — Architecture & Operations Guide (v11.11)

## 1. Overview

The overnight self-improving pipeline runs as a standalone cron job (`0 3 * * *`) on the SOC control plane. It consumes the advisory queue produced by daytime triage, performs multi-model analysis with quota-aware fallbacks, and applies verified fixes through a test-gated commit gate. Zero network mutations occur outside the LLM providers; all code changes are local, git-tracked, and pytest-validated before merge. **No `git push` is ever executed by the pipeline.**

**Entry point**: `overnight/self_improver.py::main()`
**State files**: `overnight/fix_backlog.json`, `overnight/openrouter_quota.json`, `overnight/advisory_queue.jsonl`
**Lock file**: `overnight/.pipeline.lock` (prevents concurrent runs)

---

## 2. Advisory Generationrchitecture

### 2.1 Advisory Generation — Gemini Pre-fill (`overnight/self_improver.py::phase_a_prefill`)

```python
async def phase_a_prefill(advisories: list[Advisory]) -> list[PrefillResult]:
    client = LLMClient(provider="gemini", model="gemini-1.5-flash")
    results = []
    for adv in advisories:
        prompt = PREFILL_TEMPLATE.render(advisory=adv, context=load_context(adv))
        resp = await client.complete(prompt, max_tokens=2048, temperature=0.1)
        results.append(PrefillResult(advisory_id=adv.id, draft=resp.text, tokens=resp.usage))
    return results
```

- **Purpose**: Generate initial fix drafts for all advisories in a single cheap pass.
- **Model**: `gemini-1.5-flash` (1M token context, $0.075/1M input).
- **Output**: `PrefillResult` objects serialized to `overnight/phase_a_prefill.jsonl`.
- **Failure mode**: If Gemini quota exhausted, skip Advisory Generation and proceed to Shadow Canary with empty drafts.

### 2.2 Shadow Canary — Analysis with Fallback Chain (`overnight/self_improver.py::phase_b_analyze`)

```python
async def phase_b_analyze(prefills: list[PrefillResult]) -> list[AnalysisResult]:
    client = LLMClient()  # full fallback chain: openrouter -> groq -> gemini
    results = []
    for pf in prefills:
        prompt = ANALYSIS_TEMPLATE.render(prefill=pf, backlog=load_backlog())
        resp = await client.complete_with_fallback(
            prompt,
            primary="openrouter/anthropic/claude-3.5-sonnet",
            fallbacks=["groq/llama-3.1-70b-versatile", "gemini/gemini-1.5-pro"],
            max_tokens=4096,
            temperature=0.2,
        )
        results.append(AnalysisResult(
            advisory_id=pf.advisory_id,
            fix_plan=resp.text,
            model_used=resp.model,
            provider=resp.provider,
            tokens=resp.usage,
        ))
    return results
```

- **Fallback chain**: OpenRouter (Claude 3.5 Sonnet) → Groq (Llama 3.1 70B) → Gemini (1.5 Pro).
- **Token-aware pacing**: `LLMClient` tracks per-provider token budgets; pauses 2s per 10k tokens emitted.
- **Cooldown tracking**: 60s cooldown after any 429/503; persisted in `overnight/llm_cooldown.json`.
- **Exponential backoff**: Base 1s, max 60s, jitter ±25%.
- **Rate-limit header pre-emption**: Reads `x-ratelimit-remaining`, `x-ratelimit-reset`; sleeps proactively.
- **Model curation**: Only curated models in `overnight/models.yaml` are eligible; auto-updated weekly via `overnight/update_model_catalog.py`.
- **All-providers-exhausted behavior**: If every provider is in cooldown or returns errors, `complete_with_fallback` raises `AllProvidersExhausted`. The pipeline catches this and exits with code **75 (EX_TEMPFAIL)** so the systemd timer (`overnight-pipeline.timer`) will retry on the next scheduled run.

### 2.3 Backlog Drain — Backlog Drain (`overnight/self_improver.py::phase_c_drain`)

```python
async def phase_c_drain(analyses: list[AnalysisResult]) -> DrainReport:
    applied = []
    failed = []
    for ar in analyses:
        if ar.fix_plan.confidence < 0.85:
            failed.append((ar.advisory_id, "low_confidence"))
            continue
        result = await apply_auto_fix(ar.fix_plan, dry_run=False)
        if result.success:
            applied.append(ar.advisory_id)
            record_fix(ar.advisory_id, ar.fix_plan, result.diff)
        else:
            failed.append((ar.advisory_id, result.error))
            requeue_advisory(ar.advisory_id, reason=result.error)
    return DrainReport(applied=applied, failed=failed, timestamp=utcnow())
```

- **Confidence gate**: Only fixes with `confidence >= 0.85` proceed.
- **Re-queue**: Failed items return to `overnight/advisory_queue.jsonl` with backoff metadata.
- **Idempotency**: `apply_auto_fix` is idempotent; re-running on same advisory produces no-op diff.

---

## 3. LLM Client — Multi-Provider Fallback Chain (`overnight/llm_client.py`)

### 3.1 Provider Abstraction

```python
class LLMProvider(Protocol):
    async def complete(self, prompt: str, **kwargs) -> LLMResponse: ...
    def estimate_tokens(self, text: str) -> int: ...
    def get_rate_limit_headers(self) -> dict[str, str]: ...

class OpenRouterProvider(LLMProvider):
    BASE_URL = "https://openrouter.ai/api/v1"
    MODELS = ["anthropic/claude-3.5-sonnet", "anthropic/claude-3-haiku", "meta-llama/llama-3.1-405b"]

class GroqProvider(LLMProvider):
    BASE_URL = "https://api.groq.com/openai/v1"
    MODELS = ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]

class GeminiProvider(LLMProvider):
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    MODELS = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"]
```

### 3.2 Fallback Logic (`LLMClient.complete_with_fallback`)

```python
async def complete_with_fallback(
    self,
    prompt: str,
    primary: str,
    fallbacks: list[str],
    **kwargs
) -> LLMResponse:
    chain = [primary] + fallbacks
    last_error = None
    for model_spec in chain:
        provider_name, model = model_spec.split("/", 1)
        provider = self._get_provider(provider_name)
        if not provider.is_healthy():
            continue
        if not self._quota_allows(provider_name, model, kwargs.get("max_tokens", 4096)):
            continue
        try:
            resp = await provider.complete(prompt, model=model, **kwargs)
            self._record_success(provider_name, model, resp.usage)
            return resp
        except RateLimitError as e:
            self._record_rate_limit(provider_name, e.retry_after)
            last_error = e
        except ProviderError as e:
            self._record_error(provider_name, e)
            last_error = e
    raise AllProvidersExhausted(last_error)
```

### 3.3 Token-Aware Pacing & Cooldown

- **Token budget**: Per-provider daily token limits in `overnight/token_budgets.yaml`.
- **Pacing**: `await asyncio.sleep(tokens_emitted / 10000 * 2)` after each completion.
- **Cooldown file**: `overnight/llm_cooldown.json` — `{ "openrouter": 1724563200, "groq": 0 }` (unix timestamp until ready).
- **Health check**: `provider.is_healthy()` returns `False` if cooldown active or 3+ consecutive errors.

### 3.4 Rate-Limit Header Pre-emption

```python
def _update_from_headers(self, provider: str, headers: dict):
    remaining = int(headers.get("x-ratelimit-remaining", "1"))
    reset_ts = int(headers.get("x-ratelimit-reset", "0"))
    if remaining <= 2:
        self._cooldowns[provider] = reset_ts + 5  # 5s buffer
        atomic_write_json("overnight/llm_cooldown.json", self._cooldowns)
```

---

## 4. OpenRouter Quota Manager (`overnight/openrouter_quota.py`)

### 4.1 50 RPD Enforcement

```python
class OpenRouterQuota:
    DAILY_LIMIT = 50
    QUOTA_FILE = Path("overnight/openrouter_quota.json")
    LOCK_FILE = Path("overnight/openrouter_quota.lock")

    def __init__(self):
        self._data = self._load()
        self._lock = FileLock(self.LOCK_FILE)  # requires `filelock` PyPI package

    def _load(self) -> dict:
        if self.QUOTA_FILE.exists():
            return json.loads(self.QUOTA_FILE.read_text())
        return {"date": utc_date(), "used": 0, "locked_until": 0}

    def consume(self, n: int = 1) -> bool:
        with self._lock:
            self._maybe_rollover()
            if self._data["locked_until"] > time.time():
                return False
            if self._data["used"] + n > self.DAILY_LIMIT:
                self._data["locked_until"] = next_utc_midnight()  # returns Unix timestamp (float)
                self._save()
                return False
            self._data["used"] += n
            self._save()
            return True

    def _maybe_rollover(self):
        today = utc_date()  # returns "YYYY-MM-DD" string in UTC
        if self._data["date"] != today:
            self._data = {"date": today, "used": 0, "locked_until": 0}
            self._save()
```

### 4.2 Atomic Writes & UTC Rollover

- **Atomic write**: Write to `.tmp`, `os.replace()` over target (POSIX atomic, cross-filesystem safe).
- **UTC rollover**: `utc_date()` returns `YYYY-MM-DD` in UTC; rollover at 00:00 UTC.
- **24h lock**: When limit hit, `locked_until` set to next midnight UTC (Unix timestamp via `next_utc_midnight()`); no requests until rollover.
- **Monitoring**: `cat overnight/openrouter_quota.json | jq '.used + "/" + (.DAILY_LIMIT|tostring)'`

---

## 5. Disk-Backed Advisory Queue & Fix Backlog

### 5.1 Advisory Queue (`overnight/advisory_queue.jsonl`)

```jsonl
{"id": "adv-20241219-001", "type": "false_positive", "rule_id": "wazuh-5710", "context": {...}, "created": "2024-12-19T14:32:11Z", "attempts": 0, "backoff_until": 0}
{"id": "adv-20241219-002", "type": "missing_enrichment", "rule_id": "suricata-2024321", "context": {...}, "created": "2024-12-19T15:01:44Z", "attempts": 1, "backoff_until": 1734633600}
```

- **Append-only**: Daytime workers `engine/queue_manager.py::enqueue_advisory()` append lines.
- **Crash resilience**: JSONL survives partial writes; reader skips malformed lines.
- **Decoupled analysis/fixing**: Advisory Generation/B read queue; Backlog Drain drains; no in-memory coupling.

### 5.2 Fix Backlog (`overnight/fix_backlog.json`)

```json
{
  "applied": [
    {"id": "adv-20241218-003", "fix_hash": "a1b2c3d4", "diff": "...", "test_result": "passed", "committed": true, "timestamp": "2024-12-18T03:14:22Z"}
  ],
  "pending": [
    {"id": "adv-20241219-001", "fix_plan": {...}, "confidence": 0.92, "created": "2024-12-19T03:00:11Z"}
  ],
  "rejected": [
    {"id": "adv-20241218-005", "reason": "pytest_failed", "details": "test_sanitization.py::test_ipv6_parse FAILED", "timestamp": "2024-12-18T03:15:01Z"}
  ]
}
```

- **Atomic updates**: `atomic_write_json()` used for all mutations (uses `os.replace()`).
- **Deduplication**: `fix_hash` = SHA256 of unified diff; prevents re-applying identical fixes.
- **Audit trail**: Full history retained for 90 days (configurable via `overnight/retention.yaml`).

---

## 6. Apply Auto-Fix Safety Contract (`overnight/apply_auto_fix.py`)

### 6.1 Contract Guarantees

| Guarantee | Mechanism |
|-----------|-----------|
| **Test-gated commits** | `pytest -x -q --testmon` must pass before `git commit` |
| **Crash recovery** | `.orig_backup` created before any file write; auto-restore on exception |
| **Git no-op detection** | `git diff --exit-code` — if clean, skip commit & tag as `no-op` |
| **120s timeout** | `asyncio.wait_for(apply_fix(), timeout=120)` — kills stuck processes |
| **No network mutations** | Zero outbound calls except LLM providers; all FS ops local; **no `git push`** |
| **Git identity** | Pipeline user must have `git config user.email` and `user.name` set (systemd `Environment=` or `/etc/gitconfig`) |
| **Pre-commit bypass** | `git commit --no-verify` skips hooks that may call network or exceed timeout |

### 6.2 Implementation

```python
async def apply_auto_fix(fix_plan: FixPlan, dry_run: bool = False) -> ApplyResult:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo(".")
        # 1. Create .orig_backup for each target file
        for file_path in fix_plan.target_files:
            shutil.copy2(file_path, f"{file_path}.orig_backup")
        # 2. Apply patches
        for patch in fix_plan.patches:
            apply_patch(patch, repo.working_dir)
        # 3. Run pytest gate (testmon for incremental selection)
        if not dry_run:
            result = await asyncio.wait_for(
                run_pytest(fix_plan.related_tests, use_testmon=True),
                timeout=120
            )
            if result.returncode != 0:
                restore_orig_backups(fix_plan.target_files)
                return ApplyResult(success=False, error=f"pytest_failed: {result.stderr}")
        # 4. Git no-op check
        if not dry_run and repo.git.diff("--exit-code") == 0:
            restore_orig_backups(fix_plan.target_files)
            return ApplyResult(success=True, no_op=True)
        # 5. Commit — ONLY stage files that were actually modified
        if not dry_run:
            repo.git.add(update=True)  # stages only tracked files with changes; ignores untracked
            repo.git.commit("-m", f"auto-fix: {fix_plan.advisory_id}", "--no-verify")
            tag = f"auto-fix/{fix_plan.advisory_id}/{utcnow().strftime('%Y%m%d-%H%M%S')}"
            repo.create_tag(tag)
    return ApplyResult(success=True, diff=repo.git.diff("HEAD~1"))
```

### 6.3 Crash Recovery

- On any exception: `restore_orig_backups()` copies `.orig_backup` → original.
- `.orig_backup` files cleaned up only on successful commit.
- If process killed (SIGKILL), backups remain; next run detects and restores via `overnight/recover_backups.py`.

---

## 7. Cross-Model Validation (Gemini Critique)

### 7.1 Critique Loop

```python
async def cross_model_validate(fix_plan: FixPlan, primary_resp: LLMResponse) -> ValidationResult:
    critic = LLMClient(provider="gemini", model="gemini-1.5-pro")
    prompt = CRITIQUE_TEMPLATE.render(
        fix_plan=fix_plan,
        primary_analysis=primary_resp.text,
        primary_model=primary_resp.model,
    )
    critique = await critic.complete(prompt, max_tokens=2048, temperature=0.0)
    return parse_critique(critique.text)
```

### 7.2 Hallucination Detection

Critique prompt explicitly asks:
1. Does the fix address the root cause or only symptoms?
2. Are there any invented APIs, functions, or imports not in the codebase?
3. Does the diff introduce regressions in related modules?
4. Confidence score (0.0–1.0) for the fix as written.

**Threshold**: Fix proceeds only if `critique.confidence >= 0.8` AND no hallucination flags raised.

### 7.3 Example Critique Output

```json
{
  "confidence": 0.87,
  "hallucinations": [],
  "regressions": ["engine/sanitization_pipeline.py:142 — removes IPv6 normalization added in v11.3"],
  "suggestions": ["Preserve normalize_ipv6() call; only adjust regex for CIDR parsing"],
  "verdict": "conditional_approve"
}
```

---

## 8. Operations Runbook

### 8.1 Launch Commands

```bash
# Manual run (foreground, verbose)
cd /opt/local-soc-slm
python -m overnight.self_improver --verbose --dry-run

# Production run (via systemd timer)
systemctl start overnight-pipeline.service
systemctl status overnight-pipeline.timer

# Force re-run after quota reset
rm overnight/openrouter_quota.json overnight/llm_cooldown.json
python -m overnight.self_improver
```

### 8.2 Monitoring One-Liners

```bash
# Pipeline status (last run)
jq -r '.timestamp, .applied|length, .failed|length' overnight/phase_c_drain_report.json

# OpenRouter quota
watch -n 60 'cat overnight/openrouter_quota.json | jq "{used, limit: 50, locked: .locked_until > now}"'

# LLM cooldowns
cat overnight/llm_cooldown.json | jq 'to_entries[] | select(.value > now)'

# Advisory queue depth
wc -l overnight/advisory_queue.jsonl

# Fix backlog health
jq '{applied: .applied|length, pending: .pending|length, rejected: .rejected|length}' overnight/fix_backlog.json

# Recent git auto-fix tags
git tag -l "auto-fix/*" --sort=-creatordate | head -20
```

### 8.3 Budget Checks

```bash
# Estimated monthly cost (based on last 30 days)
python -m overnight.cost_report --days 30
# Output:
# Provider       Requests   Input Tokens   Output Tokens   Est. Cost
# openrouter     1,240      45.2M          12.8M           $23.40
# groq           3,100      89.1M          34.5M           $0.00 (free tier)
# gemini         890        22.4M          8.1M            $2.15
# TOTAL                                                    $25.55
```

### 8.4 Safety Guarantees Checklist

- [ ] **Test-gated commits only**: `apply_auto_fix` runs `pytest -x -q --testmon` before any `git commit`.
- [ ] **No network mutations**: Pipeline only reads/writes local FS and calls LLM APIs (HTTPS, read-only prompts). **Git operations are strictly local; no `git push` is performed.**
- [ ] **Git audit trail**: Every fix tagged `auto-fix/<advisory_id>/<timestamp>`; `git log --oneline --grep=auto-fix` shows full history.
- [ ] **Rollback capability**: `git revert <tag>` or `git checkout <tag>^ -- <file>` restores pre-fix state.
- [ ] **Quota hard limits**: OpenRouter 50 RPD enforced at client + server; Gemini/Groq free tiers monitored.
- [ ] **Concurrency lock**: `overnight/.pipeline.lock` prevents overlapping runs (cron + manual).
- [ ] **Secrets**: API keys in `/etc/local-soc-slm/llm_keys.env` (600, root:root); never in repo.
- [ ] **Git identity configured**: `git config --global user.email "pipeline@local-soc-slm" && git config --global user.name "Overnight Pipeline"` (or via systemd `Environment=`).
- [ ] **Pre-commit hooks bypassed**: `git commit --no-verify` prevents external network calls or slow linters from breaking the 120s timeout.

---

## 9. Troubleshooting

| Symptom | Diagnosis | Resolution |
|---------|-----------|------------|
| Pipeline stuck at Shadow Canary | All providers in cooldown | `cat overnight/llm_cooldown.json`; wait or manually clear |
| OpenRouter 429 despite quota | Header pre-emption missed | Check `x-ratelimit-reset` in logs; increase buffer |
| `apply_auto_fix` timeout | Test suite hangs | Add `--timeout=60` to pytest; investigate flaky test; ensure `--testmon` is used |
| Fix rejected: `pytest_failed` | Fix breaks existing tests | Review `fix_backlog.json` rejected entry; adjust fix plan |
| Advisory re-queued repeatedly | Confidence < 0.85 or critique veto | Inspect Shadow Canary analysis + critique; may need manual triage |
| Pipeline exits with code 75 | All LLM providers exhausted (cooldown/error) | Systemd timer will retry automatically; check `llm_cooldown.json` |
| `git commit` fails with "author identity unknown" | Git user not configured for pipeline user | Set `git config user.email/name` in systemd unit or `/etc/gitconfig` |

---

## 10. File Reference

| Path | Purpose |
|------|---------|
| `overnight/self_improver.py` | Main pipeline orchestrator (Phases A/B/C) |
| `overnight/llm_client.py` | Multi-provider client, fallback, pacing, cooldown |
| `overnight/openrouter_quota.py` | 50 RPD quota manager with atomic writes |
| `overnight/apply_auto_fix.py` | Safety-contract fix application |
| `overnight/cross_validate.py` | Gemini critique loop |
| `overnight/models.yaml` | Curated model catalog (auto-updated) |
| `overnight/token_budgets.yaml` | Per-provider daily token limits |
| `overnight/advisory_queue.jsonl` | Disk-backed advisory queue (append-only) |
| `overnight/fix_backlog.json` | Applied/pending/rejected fix history |
| `overnight/openrouter_quota.json` | OpenRouter daily usage + lock state |
| `overnight/llm_cooldown.json` | Per-provider cooldown timestamps |
| `overnight/phase_a_prefill.jsonl` | Advisory Generation intermediate output |
| `overnight/phase_c_drain_report.json` | Backlog Drain summary (applied/failed) |
| `overnight/recover_backups.py` | Crash recovery for `.orig_backup` files |
| `overnight/update_model_catalog.py` | Weekly model catalog refresh |
| `overnight/cost_report.py` | Budget estimation from usage logs |

---

## 11. Dependencies

| Package | Purpose | Version Constraint |
|---------|---------|-------------------|
| `filelock` | Cross-process file locking for quota/cooldown files | `>=3.12` |
| `gitpython` | Git operations (commit, tag, diff) | `>=3.1.40` |
| `httpx` | Async HTTP client for LLM providers | `>=0.27` |
| `pyyaml` | Config parsing (models.yaml, token_budgets.yaml) | `>=6.0` |
| `tenacity` | Retry/backoff logic (optional, used in providers) | `>=8.2` |
| `pytest-testmon` | Incremental test selection for fast pytest gate | `>=1.4` |

Install via: `pip install -r overnight/requirements.txt`

---

## 12. Integration Points

- **Daytime intake**: `engine/queue_manager.py::enqueue_advisory()` → `overnight/advisory_queue.jsonl`
- **Enrichment context**: `orchestrator/context_stitcher.py::build_context(advisory)` used in Advisory Generation/B prompts
- **Model registry**: `orchestrator/model_registry.py` provides model metadata for curation
- **Memory/RAG**: `memory/embeddings.py::search_similar(advisory.text, k=5)` injects historical fixes into prompts
- **Retention**: `memory/retention.py` purges `fix_backlog.json` entries older than 90 days

---

## 13. Atomic Write Utility (`overnight/utils/atomic_write.py`)

```python
import os
import json
from pathlib import Path

def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically using os.replace (POSIX atomic, cross-filesystem safe)."""
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    os.replace(tmp_path, path)  # atomic on POSIX; replaces target even across filesystems
```

Used by: `openrouter_quota.py`, `llm_client.py` (cooldown), `fix_backlog.json` mutations.

---

*Document version: v11.11 — Generated for LOCAL-SOC-SLM overnight pipeline operators*

