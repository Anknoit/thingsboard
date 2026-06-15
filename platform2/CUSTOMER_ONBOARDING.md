# NavNet — Operator Onboarding Guide

**Tasaar NavNet** — *See everything. Fix anything.*

This guide walks through installing, configuring, and operating NavNet from first boot to day-2 operations.

---

## Prerequisites

| Requirement | Minimum | Recommended |
|---|---|---|
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Disk | 60 GB SSD | 200 GB SSD |
| Docker | 25.0+ | latest |
| Docker Compose | v2.24+ | latest |
| Open ports (inbound) | 80, 443, 1883 | 80, 443, 1883, 8883 (MQTT TLS) |

---

## Section 0 — Quick Start: Docker Deployment

This section covers the complete deployment sequence from a fresh machine to a running NavNet stack. The entire platform runs inside Docker — no Python, Java, or Node.js installation is required on your host.

### 0.1 Prerequisites check

```bash
docker --version          # Docker Engine 24+
docker compose version    # Docker Compose v2 (not the legacy docker-compose v1)
make --version            # GNU Make
```

### 0.2 Create your `.env` file

```bash
cd /opt/navnet
cp .env.example .env
nano .env
```

Set at minimum these four values:

```env
REGISTRY_ADMIN_PASSWORD=your-secure-password        # min 12 chars
REGISTRY_DB_PASSWORD=your-db-password
P2_DB_PASSWORD=your-p2-db-password
SECRET_KEY=your-64-char-random-string         # generate: openssl rand -hex 32
```

Set your AI provider key:

```env
LLM_PROVIDER=claude          # claude | openai | ollama
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=...         # if using openai
# OLLAMA_BASE_URL=http://ollama:11434   # if self-hosting
```

### 0.3 Build Docker images

```bash
make build
```

Builds the `fastapi` and `simulator` images from their Dockerfiles. Only required on first run or after a code change.

### 0.4 Start the core stack

```bash
make start
```

Starts services in dependency order:

```
Zookeeper → Kafka → PostgreSQL → Redis → ChromaDB → NavNet Registry → FastAPI
```

NavNet Registry initialises its schema on first boot — allow **2–3 minutes** before all health checks pass. Follow progress with:

```bash
make logs           # all services
make logs-fastapi   # AI service only
```

### 0.5 Verify the stack is healthy

```bash
make status
```

All containers should show `Up (healthy)`. The AI service health endpoint should return:

```json
{
  "status": "healthy",
  "services": {
    "postgres": "ok",
    "redis": "ok",
    "chroma": "ok",
    "kafka": "ok",
    "registry": "ok",
    "llm": "ok"
  },
  "models_loaded": {
    "isolation_forest": ["hvac", "energy", "network", "infra"],
    "lstm": ["hvac"],
    "gnn": true
  }
}
```

### 0.6 First-time initialisation (run once)

```bash
# Run database migrations
make migrate

# Register devices in the registry and generate MQTT credentials
make onboard

# Generate 30-day synthetic baseline and train anomaly models (~3 min)
make generate-baseline

# Optional: seed device manuals into the RAG knowledge base
# (drop PDFs into knowledge_base/docs/ first)
make seed-knowledge
```

### 0.7 Access the platform

| Service | URL | Notes |
|---|---|---|
| **NavNet UI** | `http://<server>:8080` | Dashboards, devices, alarms |
| **AI Service API** | `http://<server>:8000/docs` | Swagger UI for all AI endpoints |
| **AI Health** | `http://<server>:8000/health` | Service and model status |
| **ChromaDB** | `http://<server>:8002` | Vector store (internal) |

Default login: `tenant@navnet.local` / `<REGISTRY_ADMIN_PASSWORD>`

### 0.8 Docker service map

| Container | Image | Purpose |
|---|---|---|
| `thingsboard` | `thingsboard/tb-postgres` | Device registry, MQTT broker, UI |
| `postgres` | `timescale/timescaledb` | NavNet Registry DB + NavNet AI data |
| `kafka` | `confluentinc/cp-kafka` | Telemetry message bus |
| `zookeeper` | `confluentinc/cp-zookeeper` | Kafka coordination |
| `redis` | `redis:alpine` | Rate limiting and dedup cache |
| `chroma` | `chromadb/chroma` | RAG vector store |
| `fastapi` | *(built locally)* | Chat, anomaly, predictive, GNN services |
| `simulator` | *(built locally)* | MQTT simulator + fault injector (demo only) |

### 0.9 Common day-to-day commands

```bash
make stop                          # stop all services (data volumes preserved)
make restart                       # restart all services
make logs-fastapi                  # tail AI service logs
make logs-follow SERVICE=kafka     # follow a specific service
make shell                         # bash shell inside FastAPI container
make shell-db                      # psql into platform2 database
make backup                        # backup PostgreSQL + ChromaDB
make clean-all                     # DESTRUCTIVE: wipe containers and volumes
```

### 0.10 Production hardening

Apply the production overlay to enable resource limits, restrict ports to localhost, and run 4 Uvicorn workers:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# or via Makefile (set PRODUCTION=true in your CI/CD env)
```

Production changes: external PostgreSQL/Redis/Kafka ports are removed, NavNet Registry HTTP binds to `127.0.0.1` only (put Nginx or a load balancer in front), FastAPI runs with `--workers 4 --loop uvloop`.

---

## Section 1 — First-Time Installation

### 1.1 Clone and configure

```bash
# Clone the NavNet package to your server
cd /opt
sudo git clone <your-repo-url> navnet
sudo chown -R $USER:$USER /opt/navnet
cd /opt/navnet
```

### 1.2 Set environment variables

```bash
cp .env.example .env
nano .env
```

Fill in every value marked `REQUIRED`:

```ini
# NavNet — Environment Configuration

# ── REQUIRED: change all of these before first start ──────────────────────────

# Platform admin credentials
REGISTRY_ADMIN_PASSWORD=<strong-password>        # min 12 chars

# Database passwords
REGISTRY_DB_PASSWORD=<strong-password>
P2_DB_PASSWORD=<strong-password>

# Application secret (generate with: openssl rand -hex 32)
SECRET_KEY=<64-char-hex>

# ── AI provider — choose ONE ───────────────────────────────────────────────────
LLM_PROVIDER=claude                        # claude | openai | ollama
ANTHROPIC_API_KEY=<your-anthropic-key>     # required if LLM_PROVIDER=claude
# OPENAI_API_KEY=<key>                     # required if LLM_PROVIDER=openai
# OLLAMA_BASE_URL=http://ollama:11434      # required if LLM_PROVIDER=ollama
```

### 1.3 Start the stack

```bash
make start
```

This starts: NavNet core, AI services, message bus, time-series database, cache, and vector store.

Verify all services are healthy:

```bash
make status
```

Expected output includes `healthy` for all services. Allow up to 3 minutes for first boot.

---

## Section 2 — Device Onboarding

### 2.1 Prepare your device list

Edit `scripts/devices_sample.csv` with your actual devices, or create a new CSV with the same columns:

```
name,device_class,floor,zone,label
AHU-North,hvac,G,North Wing,Air Handling Unit
MSB-Main,energy,B1,Main Switch Board,Main Switch Board
SW-Core-01,network,B1,Main IDF,Core Switch
SRV-App-01,infra,B1,Server Room,Application Server
```

Supported `device_class` values: `hvac`, `energy`, `network`, `infra`, `occupancy`, `elevator`, `fire`

### 2.2 Run onboarding

```bash
make onboard
```

This registers all devices, creates the asset hierarchy (Site → BMS / NMS), and writes MQTT credentials to `simulator/credentials.csv`.

### 2.3 Configure device firmware

Each physical device needs its MQTT access token from `simulator/credentials.csv`. Configure the device to publish to:

```
Broker:  <server-IP>
Port:    1883  (or 8883 for TLS)
Topic:   v1/devices/me/telemetry
Token:   <access_token from credentials.csv>
```

Payload format (JSON):

```json
{
  "temperature": 22.4,
  "humidity": 48.2,
  "power_consumption": 3.1
}
```

Keys must match the feature set for the device class:

| Device class | Required telemetry keys |
|---|---|
| `hvac` | `temperature`, `humidity`, `power_consumption`, `fan_speed`, `co2_level`, `vibration_rms`, `current_draw` |
| `energy` | `active_power`, `reactive_power`, `current`, `voltage`, `power_factor` |
| `network` | `rx_bytes`, `tx_bytes`, `error_rate`, `latency`, `packet_loss` |
| `infra` | `cpu_usage`, `memory_usage`, `disk_io`, `temperature`, `error_count` |

---

## Section 3 — Dashboard Setup

### 3.1 Import rule chains

Log into the NavNet portal at `http://<server>:8080`.

Navigate to **Rule Chains** and import both files from `rule_chains/`:

1. `rule_chains/telemetry_routing.json` — routes device telemetry to AI services
2. `rule_chains/alarm_webhook.json` — triggers AI enrichment on every alarm

Set `alarm_webhook.json` as the **root rule chain**.

### 3.2 Register widgets

Follow the instructions in `widgets/WIDGET_REGISTRATION.md` to register:

- **NavNet Chat** (`widgets/navnet_chat.html`) — conversational AI for any device
- **NavNet WorkOrders** (`widgets/navnet_workorders.html`) — predictive maintenance queue

In each widget's settings, set:

```
FASTAPI_URL = http://<server>:8000
```

### 3.3 Build your dashboard

Create a new dashboard and add the widgets to device panels. Both widgets automatically detect the device entity from the dashboard context — no additional configuration required.

---

## Section 4 — AI Model Training

Run this sequence after at least 48 hours of live telemetry data. For a faster start, use the synthetic baseline generator first.

### Option A — Live data training (recommended after 48hr of data)

```bash
make train-all
```

This runs in sequence: anomaly detection → LSTM predictive → topology graph → GNN root cause.

Estimated time: 5–15 minutes depending on device count.

### Option B — Synthetic baseline (use on day 1 before live data)

```bash
make generate-baseline
```

Generates 30 days of synthetic telemetry, trains anomaly detection models, and validates them. Switch to live data training after real data accumulates.

### Training individual models

```bash
make train-anomaly      # Isolation Forest — anomaly detection per device class
make train-lstm         # LSTM — failure prediction (24–72 hour horizon)
make build-topology     # NetworkX graph from live device relations
make train-gnn          # GNN — cascade root cause (requires 5+ historical cascades)
```

---

## Section 5 — Knowledge Base

The AI chat capability improves significantly when you load device-specific documentation.

### 5.1 Add documents

Place PDF or text files in `knowledge_base/docs/`:

```bash
cp /path/to/AHU-manual.pdf knowledge_base/docs/
cp /path/to/network-topology.txt knowledge_base/docs/
```

### 5.2 Seed the knowledge base

```bash
make seed-knowledge
```

Optionally seed fault history (improves resolution recommendations):

```bash
make seed-faults
```

---

## Section 6 — Day-2 Operations

### Checking system health

```bash
make status              # container status + AI service health API
```

The health endpoint returns a full service status:

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "services": {
    "postgres": "ok",
    "redis": "ok",
    "chroma": "ok",
    "kafka": "ok",
    "registry": "ok",
    "llm": "ok"
  },
  "models_loaded": {
    "isolation_forest": ["hvac", "energy", "network", "infra"],
    "lstm": ["hvac", "energy", "network", "infra"],
    "gnn": true
  }
}
```

### Viewing logs

```bash
make logs               # all services, last 50 lines
make logs-fastapi       # AI service logs only
make logs-follow SERVICE=kafka   # follow a specific service
```

### Backing up data

```bash
make backup             # full backup: PostgreSQL + ChromaDB vector store
make backup-pg          # database only
make backup-chroma      # vector store only
```

Backups are saved to `backups/<timestamp>/`. Schedule this daily via cron:

```cron
0 2 * * * cd /opt/navnet && make backup-pg >> /var/log/vantage-backup.log 2>&1
```

### Rebuilding the topology graph

Run after adding new devices or changing network topology:

```bash
make build-topology
```

### Retraining models

Retrain monthly or after significant changes to device fleet:

```bash
make train-all
```

---

## Section 7 — NavNet Chat — Operator Guide

**NavNet Chat** is available on every device panel. Ask questions in natural language:

| Question | What NavNet Intelligence does |
|---|---|
| *"Why is this device showing high temperature?"* | Correlates telemetry trend with alarm history, retrieves relevant maintenance docs, suggests root cause |
| *"What maintenance is due?"* | Checks LSTM predictive scores, reviews open work orders, summarises upcoming tasks |
| *"Is this a cascade or isolated fault?"* | Queries GNN root cause result, explains blast radius |
| *"Create a work order for bearing replacement"* | Extracts structured work order and saves to NavNet WorkOrders queue |

**Tips:**
- The more specific the question, the more actionable the answer
- Ask follow-up questions — context is maintained within the conversation
- Work orders are created automatically when the AI recommends an action; confirm or dismiss in NavNet WorkOrders

---

## Section 8 — NavNet WorkOrders — Operator Guide

**NavNet WorkOrders** shows all open maintenance tasks for the selected device.

### Work order lifecycle

```
OPEN  →  ACKNOWLEDGED  →  IN PROGRESS  →  RESOLVED
                       ↓
                    CANCELLED
```

### Priority levels

| Priority | Colour | Meaning |
|---|---|---|
| P1 | Red | Critical — address within 4 hours |
| P2 | Deep Orange | High — address within 24 hours |
| P3 | Orange | Medium — address within 72 hours |
| P4 | Blue | Low — schedule at next maintenance window |
| P5 | Grey | Informational — review at convenience |

### Overdue work orders

Work orders past their `due_by` date are highlighted in red. Review these first.

---

## Section 9 — Troubleshooting

### AI chat returns "service unavailable"

1. Check LLM provider: `make logs-fastapi | grep llm`
2. Verify API key is set in `.env`: `grep ANTHROPIC_API_KEY .env`
3. Test connectivity: `curl http://localhost:8000/health`

### Anomaly alarms not firing

1. Verify rule chains are imported and active (Section 3.1)
2. Check Kafka consumer: `make logs-fastapi | grep kafka`
3. Confirm telemetry is arriving: check device panel in the UI for live values
4. Confirm anomaly models are trained: `make status` → check `models_loaded`

### Predictive alarms not generating

1. Ensure LSTM models are trained: `make train-lstm`
2. Verify enough telemetry history (24+ hourly readings per device)
3. Trigger manually to test: `make run-predictive`

### Work orders not appearing

1. Check PostgreSQL is healthy: `make status`
2. Run migrations: `make migrate`
3. Check for errors: `make logs-fastapi | grep work_order`

### Container fails to start

```bash
# View startup errors
docker compose logs <service-name>

# Restart a single service
docker compose restart <service-name>

# Rebuild after code change
make build && make start
```

### Database connection errors

```bash
# Check PostgreSQL is running
make status

# Connect directly to verify
make shell-db
```

---

## Section 10 — Demo Mode

For pre-sales demonstrations, use the built-in simulator:

```bash
make demo
```

This starts the full stack plus the MQTT simulator (16 virtual devices publishing live telemetry) and the fault injector.

### Running a demo scenario

```bash
# HVAC bearing wear — watch AI detect and explain the fault
make inject SCENARIO=hvac_bearing_wear

# Network cascade — watch GNN identify root cause across 4 devices
make inject SCENARIO=nms_cascade

# Power factor degradation — predictive maintenance work order generation
make inject SCENARIO=motor_prefailure

# Stop all fault injections
make reset-injections
```

Each scenario includes a step-by-step demo script in `simulator/scenarios/<name>.json` → `demo_script` field.

### Stop demo mode

```bash
make demo-stop     # stops simulator, core stack continues running
```

---

## Support

Contact Tasaar support at support@tasaar.com with:
- Output of `make status`
- Output of `curl http://localhost:8000/health`
- Relevant log snippet from `make logs-fastapi`
