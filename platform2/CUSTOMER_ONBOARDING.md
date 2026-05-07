# Vantage NMS — Operator Onboarding Guide

**Tasaar Vantage NMS** — *See everything. Fix anything.*

This guide walks through installing, configuring, and operating Vantage NMS from first boot to day-2 operations.

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

## Section 1 — First-Time Installation

### 1.1 Clone and configure

```bash
# Clone the Vantage NMS package to your server
cd /opt
sudo git clone <your-repo-url> vantage-nms
sudo chown -R $USER:$USER /opt/vantage-nms
cd /opt/vantage-nms
```

### 1.2 Set environment variables

```bash
cp .env.example .env
nano .env
```

Fill in every value marked `REQUIRED`:

```ini
# Vantage NMS — Environment Configuration

# ── REQUIRED: change all of these before first start ──────────────────────────

# Platform admin credentials
TB_ADMIN_PASSWORD=<strong-password>        # min 12 chars

# Database passwords
TB_DB_PASSWORD=<strong-password>
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

This starts: Vantage NMS core, AI services, message bus, time-series database, cache, and vector store.

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

Log into the Vantage NMS portal at `http://<server>:8080`.

Navigate to **Rule Chains** and import both files from `rule_chains/`:

1. `rule_chains/telemetry_routing.json` — routes device telemetry to AI services
2. `rule_chains/alarm_webhook.json` — triggers AI enrichment on every alarm

Set `alarm_webhook.json` as the **root rule chain**.

### 3.2 Register widgets

Follow the instructions in `widgets/WIDGET_REGISTRATION.md` to register:

- **Vantage Chat** (`widgets/vantage_chat.html`) — conversational AI for any device
- **Vantage WorkOrders** (`widgets/vantage_workorders.html`) — predictive maintenance queue

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
    "thingsboard": "ok",
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
0 2 * * * cd /opt/vantage-nms && make backup-pg >> /var/log/vantage-backup.log 2>&1
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

## Section 7 — Vantage Chat — Operator Guide

**Vantage Chat** is available on every device panel. Ask questions in natural language:

| Question | What Vantage Intelligence does |
|---|---|
| *"Why is this device showing high temperature?"* | Correlates telemetry trend with alarm history, retrieves relevant maintenance docs, suggests root cause |
| *"What maintenance is due?"* | Checks LSTM predictive scores, reviews open work orders, summarises upcoming tasks |
| *"Is this a cascade or isolated fault?"* | Queries GNN root cause result, explains blast radius |
| *"Create a work order for bearing replacement"* | Extracts structured work order and saves to Vantage WorkOrders queue |

**Tips:**
- The more specific the question, the more actionable the answer
- Ask follow-up questions — context is maintained within the conversation
- Work orders are created automatically when the AI recommends an action; confirm or dismiss in Vantage WorkOrders

---

## Section 8 — Vantage WorkOrders — Operator Guide

**Vantage WorkOrders** shows all open maintenance tasks for the selected device.

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
