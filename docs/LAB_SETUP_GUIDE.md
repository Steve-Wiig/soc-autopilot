# soc-autopilot Lab Setup Guide v11.11

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

  # --- soc-autopilot Engine ---
  slm-engine:
    build:
      context: ..
      dockerfile: docker/engine.Dockerfile
    container_name: soc-autopilot-engine
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
    container_name: soc-autopilot-overnight
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
git clone https://github.com/your-org/soc-autopilot.git
cd soc-autopilot

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