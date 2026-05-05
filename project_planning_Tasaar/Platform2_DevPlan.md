# Platform 2 — IoT Operations Intelligence
## Development Plan

> **Stack:** ThingsBoard CE · FastAPI · LangChain · Chroma · PyTorch · Kafka · PostgreSQL · Docker  
> **Delivery:** On-premise, single-organisation deployment  
> **Timeline:** 20 days to demo-ready MVP

---

## What This Platform Does

A unified IoT device operations intelligence platform for building and network devices. Facility managers, NOC engineers, and field technicians use it to detect faults in real time, resolve them by chatting with an AI that has full device context, and prevent failures through predictive maintenance.

**ThingsBoard CE** handles everything a standard device management platform should — device registry, live dashboards, alarm management, rule chains, multi-protocol ingestion, user roles, and floor plan views. It is deployed as-is with no UI customisation.

**Your codebase** is four FastAPI AI microservices and two lightweight HTML widgets embedded in ThingsBoard dashboards. Nothing else.

---

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│              OPERATOR (ThingsBoard CE UI)               │
│  Dashboards · Alarms · Floor Maps · Device Registry     │
│                                                         │
│  ┌──────────────────────┐  ┌────────────────────────┐   │
│  │  Chat-to-Fix Widget  │  │  Work Order Widget     │   │
│  │  (custom HTML/JS)    │  │  (custom HTML/JS)      │   │
│  └──────────┬───────────┘  └──────────┬─────────────┘   │
└─────────────┼────────────────────────┼──────────────────┘
              │ SSE stream             │ REST
              ▼                        ▼
┌─────────────────────────────────────────────────────────┐
│                    FastAPI AI Services                  │
│                                                         │
│  /chat (RAG+LLM)  /anomaly  /predictive  /cascade(GNN)  │
└──────┬──────────────────┬──────────────────────────┬────┘
       │                  │                          │
       ▼                  ▼                          ▼
  Chroma            PostgreSQL                  TimescaleDB
  (vector store)    (work orders, audit)        (health scores)
       ▲
  LangChain RAG
       │
  LLM Adapter ──── Claude / GPT-4 / Ollama (env var switch)

┌─────────────────────────────────────────────────────────┐
│              ThingsBoard CE (internal)                  │
│                                                         │
│  Webhook → FastAPI /webhook/alarm  (on alarm trigger)   │
│  Kafka   → FastAPI consumers       (live telemetry)     │
│  REST API← FastAPI reads           (device metadata)    │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                     Device Layer                        │
│  BMS: HVAC · Energy · Occupancy · Elevators · Fire      │
│  NMS: Routers · BTS/RAN · Servers · Links · UPS         │
│  Protocols: MQTT · SNMP · BACnet · Modbus · gRPC        │
└─────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
platform2/
├── docker-compose.yml
├── .env.example
│
├── fastapi/
│   ├── main.py
│   ├── routers/
│   │   ├── chat.py          # RAG + LLM Chat-to-Fix
│   │   ├── webhook.py       # Alarm enrichment + GNN trigger
│   │   ├── workorders.py    # Work order CRUD
│   │   └── health.py
│   ├── services/
│   │   ├── rag.py           # LangChain pipeline
│   │   ├── llm_adapter.py   # Provider-agnostic LLM
│   │   ├── anomaly.py       # Isolation Forest
│   │   ├── predictive.py    # LSTM batch job
│   │   ├── gnn.py           # GNN root cause
│   │   └── tb_client.py     # ThingsBoard REST API wrapper
│   ├── consumers/
│   │   └── telemetry.py     # Kafka consumer → anomaly scorer
│   ├── models/
│   │   └── schemas.py       # Pydantic models
│   ├── db/
│   │   ├── postgres.py
│   │   └── migrations/
│   └── Dockerfile
│
├── widgets/
│   ├── chat_widget.html     # Chat-to-Fix TB widget
│   └── workorder_widget.html
│
├── simulator/
│   ├── mqtt_sim.py          # Device telemetry generator
│   ├── fault_injector.py    # REST-triggered fault scenarios
│   └── scenarios/
│       ├── hvac_bearing_wear.json
│       ├── nms_cascade.json
│       └── motor_prefailure.json
│
├── knowledge_base/
│   ├── seed.py              # Index documents into Chroma
│   └── docs/               # Device manuals, runbooks (PDFs)
│
└── scripts/
    ├── train_anomaly.py
    ├── train_lstm.py
    └── onboard_devices.py   # Bulk device registration via TB REST
```

---

## Environment Variables

```env
# ThingsBoard
TB_URL=http://thingsboard:8080
TB_ADMIN_USER=tenant@thingsboard.org
TB_ADMIN_PASSWORD=changeme

# FastAPI
FASTAPI_PORT=8000
SECRET_KEY=changeme

# LLM — switch provider with one value: claude | openai | ollama
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3

# Kafka
KAFKA_BOOTSTRAP=kafka:9092
KAFKA_TOPICS_BMS_HVAC=tb.telemetry.bms.hvac
KAFKA_TOPICS_BMS_ENERGY=tb.telemetry.bms.energy
KAFKA_TOPICS_BMS_OTHER=tb.telemetry.bms.other
KAFKA_TOPICS_NMS_NETWORK=tb.telemetry.nms.network
KAFKA_TOPICS_NMS_INFRA=tb.telemetry.nms.infra

# PostgreSQL
POSTGRES_URL=postgresql://p2:changeme@postgres:5432/platform2

# Redis
REDIS_URL=redis://redis:6379

# Chroma
CHROMA_HOST=chroma
CHROMA_PORT=8001
CHROMA_COLLECTION=platform2_kb

# Anomaly thresholds
ANOMALY_SIGMA_THRESHOLD=3.4
ANOMALY_BASELINE_DAYS=30

# Predictive maintenance
LSTM_FAILURE_THRESHOLD=0.75
LSTM_BATCH_HOUR=2

# GNN cascade trigger
CASCADE_ALARM_COUNT=3
CASCADE_WINDOW_SECONDS=60
```

---

## Docker Compose Services

```yaml
# All services started with: docker compose up -d
services:
  thingsboard:    # Full UI + device management + rule chains
  fastapi:        # All AI microservices
  postgres:       # Work orders + audit log (TimescaleDB)
  kafka:          # Telemetry message bus
  zookeeper:      # Kafka dependency
  redis:          # Dedup cache + rate limiting
  chroma:         # RAG vector store
  simulator:      # Demo fault injector (disable in production)
```

---

---

# Phase 1 — Infrastructure & ThingsBoard Setup
## Days 1–2

**Goal:** ThingsBoard CE running, all devices registered, Kafka telemetry flowing, rule chains wired to FastAPI. After day 2, ThingsBoard is not touched again.

---

### Task 1.1 — Docker Compose stack

Stand up the full infrastructure stack. All services must be healthy before proceeding.

```
Services to start: thingsboard, postgres, kafka, zookeeper, redis, chroma
Verify:
  - ThingsBoard UI accessible at http://localhost:8080
  - Kafka broker healthy (kafka-topics.sh --list)
  - PostgreSQL accepting connections
  - Chroma API responding at http://localhost:8001
```

**Prompt for AI:**
```
Create a docker-compose.yml for the following services with health checks and 
restart policies:
- ThingsBoard CE (thingsboard/tb-postgres, port 8080, 1883 MQTT, 5683 CoAP)
- Apache Kafka + Zookeeper (confluentinc/cp-kafka, port 9092)
- PostgreSQL with TimescaleDB extension (timescale/timescaledb, port 5432)
- Redis (redis:alpine, port 6379)
- ChromaDB (chromadb/chroma, port 8001)

All services on a bridge network called platform2-net.
Include an .env.example file with all required variables.
ThingsBoard needs these env vars for Kafka integration:
  KAFKA_ENABLED=true
  TB_KAFKA_SERVERS=kafka:9092
```

---

### Task 1.2 — ThingsBoard device schema

Define the device type hierarchy in ThingsBoard. All BMS and NMS devices registered under consistent asset groups.

```
Asset hierarchy:
  Site (e.g. "Head Office Building")
  └── BMS
  │   ├── HVAC
  │   ├── Energy
  │   ├── Occupancy
  │   ├── Elevator
  │   └── Fire_Access
  └── NMS
      ├── Network
      └── Infrastructure

Device attributes to set on every device:
  - device_class   (hvac | energy | occupancy | elevator | fire | network | infra)
  - location       (floor, zone, or rack ID)
  - protocol       (mqtt | snmp | bacnet | modbus)
  - baseline_days  (default: 30)
```

**Prompt for AI:**
```
Write a Python script using the ThingsBoard REST API to:
1. Create asset groups: Site, BMS/HVAC, BMS/Energy, BMS/Occupancy, 
   BMS/Elevator, BMS/Fire_Access, NMS/Network, NMS/Infrastructure
2. Bulk-register devices from a CSV with columns: 
   name, device_class, location, protocol, asset_group
3. Set shared attributes on each device: device_class, location, protocol, baseline_days=30
4. Return device credentials (access tokens) written to a credentials.csv

ThingsBoard base URL and admin credentials come from .env
Use the /api/device and /api/plugins/telemetry endpoints.
```

---

### Task 1.3 — ThingsBoard Kafka integration

Configure ThingsBoard to publish all device telemetry to Kafka topics partitioned by device class.

```
Topics to configure:
  tb.telemetry.bms.hvac     ← all HVAC device telemetry
  tb.telemetry.bms.energy   ← energy meters
  tb.telemetry.bms.other    ← occupancy, elevator, fire, access
  tb.telemetry.nms.network  ← routers, switches, BTS/RAN
  tb.telemetry.nms.infra    ← servers, UPS, firewalls, links

Routing logic: device_class attribute → topic mapping
```

**Prompt for AI:**
```
Write a ThingsBoard rule chain configuration (JSON export format) that:
1. Receives all incoming telemetry messages
2. Reads the device_class attribute from the originator device
3. Routes to the correct Kafka topic based on device_class:
   hvac → tb.telemetry.bms.hvac
   energy → tb.telemetry.bms.energy
   occupancy | elevator | fire | access → tb.telemetry.bms.other
   network → tb.telemetry.nms.network
   infra → tb.telemetry.nms.infra
4. Each Kafka node publishes: { ts, device_id, device_class, device_name, telemetry }

Also write the alarm rule chain that:
- Triggers a webhook POST to http://fastapi:8000/webhook/alarm when any alarm is created
- Triggers a second webhook POST to http://fastapi:8000/webhook/cascade 
  when 3+ alarms fire within 60 seconds (use a counter node with 60s window)
- Payload: { alarm_id, entity_id, entity_name, alarm_type, severity, details, ts }
```

---

### Task 1.4 — PostgreSQL schema

**Prompt for AI:**
```
Write a PostgreSQL schema with TimescaleDB for Platform 2 with these tables:

work_orders:
  id (uuid pk), entity_id (varchar), device_name (varchar), 
  device_class (varchar), fault_description (text), 
  recommended_steps (text[]), parts_required (jsonb), 
  estimated_labour_hours (float), priority (int 1-5), 
  status (open|acknowledged|in_progress|closed), 
  created_at (timestamptz), due_by (timestamptz), closed_at (timestamptz)

audit_log:
  id (uuid pk), entity_id (varchar), event_type (varchar), 
  payload (jsonb), created_at (timestamptz)

equipment_health:
  entity_id (varchar), scored_at (timestamptz), 
  health_score (float), failure_probability (float), 
  features (jsonb), model_version (varchar)
  -- make this a TimescaleDB hypertable on scored_at

anomaly_scores:
  entity_id (varchar), scored_at (timestamptz), 
  score (float), sigma (float), triggered (boolean), 
  telemetry_snapshot (jsonb)
  -- make this a TimescaleDB hypertable on scored_at

Include Alembic migration setup.
```

---

### Task 1.5 — ThingsBoard REST client

**Prompt for AI:**
```
Write a Python class TBClient in fastapi/services/tb_client.py that wraps 
the ThingsBoard REST API with these methods:

- get_device(entity_id) → device metadata dict
- get_telemetry(entity_id, keys, start_ts, end_ts) → list of {ts, values}
- get_latest_telemetry(entity_id) → dict of {key: value}
- get_alarms(entity_id, limit=10) → list of alarm dicts  
- update_alarm_attributes(alarm_id, attributes: dict) → bool
- create_alarm(entity_id, alarm_type, severity, details: dict) → alarm_id
- get_device_attributes(entity_id) → dict

Authentication: JWT token from /api/auth/login, auto-refresh on 401.
Base URL from TB_URL env var.
Use httpx with async support.
Include retry logic (3 attempts, exponential backoff).
```

---

### Checkpoint — Day 2 end

```
✓ docker compose up -d starts all services cleanly
✓ ThingsBoard UI accessible, test devices registered with correct attributes
✓ MQTT publish from simulator reaches ThingsBoard and appears in dashboard
✓ Telemetry routes to correct Kafka topic (verify with kafka-console-consumer)
✓ Alarm fires webhook POST to FastAPI /webhook/alarm (use a test endpoint returning 200)
✓ TBClient.get_device() and get_latest_telemetry() return correct data
✓ PostgreSQL migrations applied, all tables created
```

---

---

# Phase 2 — FastAPI Foundation
## Days 3–4

**Goal:** FastAPI project running with all service stubs, database connected, webhook receiving, ThingsBoard client verified.

---

### Task 2.1 — FastAPI project structure

**Prompt for AI:**
```
Create a FastAPI application in fastapi/main.py with:

1. Routers registered: chat, webhook, workorders, health
2. Lifespan handler (startup/shutdown) that:
   - Connects to PostgreSQL (SQLAlchemy async)
   - Connects to Redis
   - Connects to Chroma
   - Starts Kafka consumer as background task
3. CORS middleware allowing all origins (MVP — restrict per customer in production)
4. Structured JSON logging (structlog)
5. Global exception handler returning { error, detail, ts }

All config from environment variables via pydantic-settings BaseSettings class.
No authentication for MVP — add a note where auth middleware should go.
```

---

### Task 2.2 — Webhook receiver

**Prompt for AI:**
```
Write the FastAPI router fastapi/routers/webhook.py with two endpoints:

POST /webhook/alarm
  - Receives ThingsBoard alarm payload: 
    { alarm_id, entity_id, entity_name, alarm_type, severity, details, ts }
  - Validates payload with Pydantic
  - Checks Redis for duplicate (key: alarm:{alarm_id}, TTL 60s) — skip if seen
  - Publishes to internal asyncio queue for AI enrichment processing
  - Returns 200 immediately (do not wait for AI enrichment)
  - Background task: call anomaly service, get enrichment, 
    write ai_anomaly_score + ai_explanation back to TB via TBClient

POST /webhook/cascade  
  - Receives: { alarm_ids: list[str], entity_ids: list[str], ts }
  - Validates minimum 3 alarms
  - Publishes to GNN processing queue
  - Returns 200 immediately
  - Background task: call GNN service, write root_cause_device 
    + cascade_explanation attributes back to all alarms via TBClient

Use FastAPI BackgroundTasks for the async processing.
```

---

### Task 2.3 — Work order router

**Prompt for AI:**
```
Write fastapi/routers/workorders.py with:

GET /workorders?entity_id={id}&status={status}
  - Returns list of work orders for a device, filtered by status
  - Ordered by priority asc, created_at desc

POST /workorders
  - Creates a work order from Pydantic model
  - Returns created work order with id

PATCH /workorders/{id}/status
  - Updates status: open → acknowledged → in_progress → closed
  - Logs to audit_log table on status change
  - On close: records closed_at timestamp

GET /workorders/{id}
  - Returns single work order with full detail

All endpoints use async SQLAlchemy with the PostgreSQL connection pool.
Pydantic schemas in fastapi/models/schemas.py.
```

---

### Checkpoint — Day 4 end

```
✓ fastapi starts: uvicorn main:app --host 0.0.0.0 --port 8000
✓ GET /health returns { status: ok, services: { postgres, redis, chroma, kafka } }
✓ POST /webhook/alarm returns 200 and logs payload
✓ POST /webhook/cascade returns 200 and logs payload  
✓ GET /workorders?entity_id=test returns empty list (not 500)
✓ POST /workorders creates a record visible in PostgreSQL
✓ TBClient tested against live ThingsBoard — get_device works
```

---

---

# Phase 3 — RAG + Chat-to-Fix
## Days 5–9

**Goal:** The core product feature. Operator asks a plain-English question about a device, gets a specific actionable resolution in under 90 seconds.

---

### Task 3.1 — LLM provider adapter

**Prompt for AI:**
```
Write fastapi/services/llm_adapter.py — a provider-agnostic LLM interface.

Define an abstract base class LLMAdapter with:
  async def stream_chat(system: str, messages: list[dict]) -> AsyncIterator[str]
  async def embed(text: str) -> list[float]
  async def health_check() -> bool

Implement three concrete classes:
  ClaudeAdapter   — uses anthropic SDK, model claude-sonnet-4-20250514
  OpenAIAdapter   — uses openai SDK, model gpt-4o
  OllamaAdapter   — uses httpx to call Ollama REST API

Factory function get_llm_adapter() reads LLM_PROVIDER env var and returns 
the correct instance. All three must implement stream_chat as an async generator 
yielding string tokens.

Error handling: on provider API error, log and raise LLMProviderError with 
the provider name and original error message.
```

---

### Task 3.2 — RAG pipeline

**Prompt for AI:**
```
Write fastapi/services/rag.py — the LangChain RAG pipeline.

Components:
1. ChromaDB vector store connection (collection: platform2_kb)
   - Embeddings via the active LLMAdapter.embed() method
   
2. Retriever: top-5 documents by cosine similarity
   - Filter by device_class metadata when provided
   - Filter by document_type when provided (manual | runbook | fault_action | topology)

3. Function retrieve_context(query: str, device_class: str, k: int = 5) → list[Document]
   Returns documents with content + metadata (source, document_type, device_class)

4. Function format_rag_context(documents: list[Document]) → str
   Formats retrieved docs as numbered sections for LLM prompt injection

5. Function add_fault_resolution(entity_id, question, resolution, device_class)
   Adds a resolved fault-action pair to Chroma as a new document
   Metadata: { document_type: fault_action, device_class, entity_id, ts }

Use langchain-chroma and langchain-community.
```

---

### Task 3.3 — Device context builder

**Prompt for AI:**
```
Write fastapi/services/context_builder.py with function:

async def build_device_context(entity_id: str) -> dict

This function:
1. Calls TBClient.get_device(entity_id) → device metadata
2. Calls TBClient.get_latest_telemetry(entity_id) → current readings
3. Calls TBClient.get_telemetry(entity_id, last 48hrs) → time-series
4. Calls TBClient.get_alarms(entity_id, limit=5) → recent alarms
5. Calls TBClient.get_device_attributes(entity_id) → shared attributes

Returns a structured dict:
{
  device_name, device_class, location, protocol,
  latest_telemetry: { key: value },
  telemetry_48hr_summary: { key: { min, max, mean, trend } },
  recent_alarms: [ { type, severity, ts, details } ],
  attributes: { baseline_days, ... }
}

Cache result in Redis with TTL=30s (key: ctx:{entity_id}).
Handle TBClient errors gracefully — return partial context with error flags.
```

---

### Task 3.4 — System prompt builder

**Prompt for AI:**
```
Write fastapi/services/prompt_builder.py with function:

def build_system_prompt(device_context: dict, rag_docs: list[Document]) -> str

The system prompt must instruct the LLM to:
1. Act as an expert field operations engineer with deep knowledge of building 
   management systems and network infrastructure
2. Answer only based on the provided device context and retrieved documents
3. Always be specific — include exact values, part numbers, stock codes, 
   and time estimates when available
4. Structure every response as:
   - Root cause (one sentence)
   - Immediate action (if any — what to do right now)
   - Permanent fix (step-by-step)
   - Parts required (with stock codes if known)
   - Estimated time
5. If a work order should be created, end with a JSON block:
   ```work_order
   { "fault_description": "...", "steps": [...], "parts": [...], 
     "labour_hours": N, "priority": 1-5 }
   ```
6. If the question cannot be answered from the provided context, say so clearly 
   and suggest what additional information would help

Inject device_context as structured text and rag_docs as numbered source sections.
```

---

### Task 3.5 — Chat endpoint

**Prompt for AI:**
```
Write the FastAPI SSE streaming endpoint in fastapi/routers/chat.py:

POST /chat
Request body:
{
  entity_id: str,
  question: str,
  widget_context: {          # passed directly from TB widget
    entity_name: str,
    latest_telemetry: dict,
    last_alarm: str
  }
}

Processing:
1. Build device context: await build_device_context(entity_id)
   Merge with widget_context (widget data is more recent)
2. Retrieve RAG docs: retrieve_context(question, device_class=device_context.device_class)
3. Build system prompt: build_system_prompt(device_context, rag_docs)
4. Stream LLM response: llm_adapter.stream_chat(system, messages)
5. Parse response for ```work_order JSON block
6. If work_order block found: create work order in PostgreSQL, 
   include work_order_id in final SSE event
7. Log full exchange to audit_log

Response: text/event-stream (SSE)
  - data: {"type": "token", "content": "..."} for each token
  - data: {"type": "work_order", "id": "...", "data": {...}} if work order created
  - data: {"type": "done"} on completion
  - data: {"type": "error", "message": "..."} on failure

Rate limit: 10 requests per minute per entity_id (Redis sliding window).
```

---

### Task 3.6 — Knowledge base seeding script

**Prompt for AI:**
```
Write knowledge_base/seed.py — a script to index documents into Chroma.

Supports:
  python seed.py --dir ./docs --device-class hvac --type manual
  python seed.py --dir ./docs --device-class network --type runbook
  python seed.py --file fault_history.csv --type fault_action

For PDFs: extract text with pypdf, chunk with RecursiveCharacterTextSplitter 
  (chunk_size=1000, chunk_overlap=200)

For fault_action CSV: columns are entity_id, device_class, question, resolution, ts
  Each row becomes one document with metadata

Each document stored in Chroma with metadata:
  { source, document_type, device_class, indexed_at }

Print progress: files processed, chunks created, total documents in collection.
```

---

### Checkpoint — Day 9 end

```
✓ POST /chat with a test entity_id + question returns SSE stream
✓ SSE stream completes in under 90 seconds for a real question
✓ Device context correctly populated from ThingsBoard (telemetry, alarms, metadata)
✓ RAG retrieval returns relevant documents (verify with --verbose logging)
✓ LLM response is specific and actionable (not generic)
✓ Work order created in PostgreSQL when LLM includes ```work_order block
✓ LLM_PROVIDER=ollama works with a local Ollama instance (air-gapped test)
✓ Rate limiting blocks request 11 within the same minute
✓ seed.py successfully indexes 20 test documents into Chroma
```

---

---

# Phase 4 — ThingsBoard Custom Widgets
## Days 10–11

**Goal:** Chat-to-Fix panel and Work Order list embedded in ThingsBoard dashboards. No framework, no build step — pure HTML/JS pasted into TB widget editor.

---

### Task 4.1 — Chat-to-Fix widget

**Prompt for AI:**
```
Write a ThingsBoard custom widget (single HTML file, vanilla JS only, no npm) 
for the Chat-to-Fix feature.

ThingsBoard widget context available:
  self.ctx.datasources[0].entityId   — the device entity ID
  self.ctx.datasources[0].entityName — the device name  
  self.ctx.data                      — latest telemetry array
  self.ctx.widgetConfig              — widget settings (contains FASTAPI_URL)

The widget must:
1. On load: read entity_id, entity_name, latest_telemetry from ctx
   Display device name as widget header
   Show last 3 telemetry readings as context pills (key: value)

2. Input area: textarea (placeholder: "Ask about this device...") + Send button
   Keyboard shortcut: Ctrl+Enter to send

3. On send:
   POST to {FASTAPI_URL}/chat with:
   { entity_id, question, widget_context: { entity_name, latest_telemetry, last_alarm } }
   Read response as EventSource / fetch ReadableStream (SSE)
   Render tokens into response area as they arrive (append to div)
   Show typing indicator (three dots) during inference

4. On SSE event type=work_order:
   Render a structured work order card below the LLM response:
   - Priority badge (colour-coded 1-5)
   - Fault description
   - Steps as numbered list
   - Parts as pill tags
   - Labour estimate

5. On SSE event type=done: hide typing indicator, show copy button

6. Clear button resets the widget for a new question

Style: match ThingsBoard Material Design — use ThingsBoard CSS variables 
where possible. Widget background transparent. Font: Roboto.
No external CSS or JS libraries — everything inline.
```

---

### Task 4.2 — Work order list widget

**Prompt for AI:**
```
Write a second ThingsBoard custom widget (single HTML file, vanilla JS) 
that shows open work orders for the current device.

On load:
  GET {FASTAPI_URL}/workorders?entity_id={ctx.entityId}&status=open,acknowledged,in_progress
  Render as a card list sorted by priority

Each work order card shows:
  - Priority badge (P1-P5, colour coded: P1=red, P2=orange, P3=yellow, P4=blue, P5=grey)
  - Fault description (truncated to 2 lines)
  - Created at (relative: "2 hours ago")
  - Due by (with overdue highlighting in red if past due)
  - Status pill
  - "Update Status" dropdown: acknowledged | in_progress | closed
    On change: PATCH {FASTAPI_URL}/workorders/{id}/status

Empty state: "No open work orders for this device"
Auto-refresh every 60 seconds.
```

---

### Task 4.3 — Register widgets in ThingsBoard

```
Steps (manual — no automation):
1. ThingsBoard UI → Widget Library → Create new widget bundle: "Platform 2 AI"
2. Add widget type: "Chat-to-Fix" — paste chat_widget.html into HTML tab
3. Add widget type: "Work Orders" — paste workorder_widget.html
4. Configure widget settings schema for both:
   - FASTAPI_URL (string, required, default: http://localhost:8000)
5. Add both widgets to a test device dashboard
6. Verify Chat-to-Fix widget sends question and receives streamed response
7. Verify Work Order widget loads and status update works
```

---

### Checkpoint — Day 11 end

```
✓ Both widgets appear in ThingsBoard widget library under "Platform 2 AI"
✓ Chat-to-Fix widget: entity context pre-loaded, question submitted, SSE response streams
✓ Work order card renders when LLM returns a ```work_order block
✓ Work Order list widget: open work orders visible, status update saves to PostgreSQL
✓ Widgets work on mobile (ThingsBoard responsive layout)
✓ FASTAPI_URL is configurable per widget instance (not hardcoded)
```

---

---

# Phase 5 — Anomaly Detection
## Days 12–14

**Goal:** Isolation Forest running on live Kafka stream. Every ThingsBoard alarm automatically enriched with an AI anomaly score and plain-English explanation.

---

### Task 5.1 — Isolation Forest models

**Prompt for AI:**
```
Write fastapi/services/anomaly.py with:

Class IsolationForestService:

  train(device_class: str, training_data: list[dict]) → None
    - Extracts numeric features from telemetry dicts (device_class-specific feature set)
    - Trains an Isolation Forest (contamination=0.05, n_estimators=100)
    - Saves model to disk: models/isolation_forest_{device_class}.pkl
    - Saves feature names and scaler

  score(entity_id: str, device_class: str, telemetry: dict) → AnomalyResult
    - Loads model for device_class (cached in memory after first load)
    - Extracts and scales features
    - Returns: { score (0-100), sigma (float), is_anomaly (bool), 
                 explanation (str), features_used (dict) }
    - explanation is a plain-English sentence: 
      "Power consumption is 3.8σ above 30-day baseline (23% higher than normal)"

Feature sets by device_class:
  hvac:    temperature, humidity, power_consumption, fan_speed, co2_level
  energy:  active_power, reactive_power, current, voltage, power_factor
  network: rx_bytes, tx_bytes, error_rate, latency, packet_loss
  infra:   cpu_usage, memory_usage, disk_io, temperature, error_count

AnomalyResult as Pydantic model.
```

---

### Task 5.2 — Kafka consumer

**Prompt for AI:**
```
Write fastapi/consumers/telemetry.py — an async Kafka consumer that runs 
as a background task from FastAPI lifespan.

Consumes all five Kafka topics concurrently:
  tb.telemetry.bms.hvac, tb.telemetry.bms.energy, tb.telemetry.bms.other,
  tb.telemetry.nms.network, tb.telemetry.nms.infra

For each message:
1. Parse JSON: { ts, device_id, device_class, device_name, telemetry }
2. Call IsolationForestService.score(device_id, device_class, telemetry)
3. Write to anomaly_scores table (TimescaleDB)
4. If is_anomaly=True:
   a. Check Redis for active alarm on this device (key: active_alarm:{device_id})
   b. If alarm exists: call TBClient.update_alarm_attributes(alarm_id, {
        ai_anomaly_score: result.score,
        ai_sigma: result.sigma,
        ai_explanation: result.explanation
      })
   c. If no active alarm: create alarm in TB via TBClient.create_alarm()

Use aiokafka for async consumption.
Consumer group: platform2-anomaly
Auto-commit offsets after successful processing.
Dead letter queue: failed messages written to Kafka topic platform2.dlq
```

---

### Task 5.3 — Baseline training script

**Prompt for AI:**
```
Write scripts/train_anomaly.py — a script to train Isolation Forest models 
on historical ThingsBoard data.

Usage: python train_anomaly.py --device-class hvac --days 30

Steps:
1. Query ThingsBoard REST API for all devices of the given device_class
2. For each device: fetch telemetry for the last N days
3. Aggregate all device telemetry into a training DataFrame
4. Train IsolationForestService for the device_class
5. Print: devices used, samples collected, model saved to path

Also write scripts/generate_synthetic_baseline.py that creates 30 days of 
realistic synthetic telemetry for each device class (for use before real 
device data is available):
  - HVAC: sinusoidal temperature 18-24°C, power 2-5kW with noon peak
  - Energy: power 10-50kW with business hours pattern
  - Network: traffic 1-100 Mbps with working hours pattern, <0.1% error rate
  - Infra: CPU 20-60%, memory 40-70%, stable temperature

Inject 3 anomalies per device class for model validation.
```

---

### Checkpoint — Day 14 end

```
✓ Kafka consumer starts with FastAPI and processes messages from all 5 topics
✓ Anomaly scores written to TimescaleDB (verify with psql query)
✓ Simulated HVAC anomaly (power spike) triggers is_anomaly=True
✓ ThingsBoard alarm for anomaly device shows ai_anomaly_score and ai_explanation attributes
✓ Alarm explanation is plain English and specific (not "anomaly detected")
✓ Redis dedup prevents the same alarm being enriched twice
✓ Dead letter queue receives malformed messages (test with bad JSON)
✓ Models trained on 30-day synthetic baseline for all 5 device classes
```

---

---

# Phase 6 — Predictive Maintenance
## Days 15–16

**Goal:** LSTM model predicts equipment failure 24-72 hours ahead. Predictive alarm appears in ThingsBoard alarm feed before anything breaks.

---

### Task 6.1 — LSTM model

**Prompt for AI:**
```
Write fastapi/services/predictive.py with:

Class LSTMPredictiveService:

  train(device_class: str, training_data: DataFrame) → None
    - Features: sequence of [vibration_rms, current_draw, temperature, error_count]
    - Sequence length: 24 time steps (24 hours of hourly readings)
    - Label: binary failure_in_72hr (1 if failure occurred within 72hrs of sequence end)
    - LSTM architecture: 2 LSTM layers (64, 32 units) + Dense(1, sigmoid)
    - Saves model: models/lstm_{device_class}.pth
    - Saves feature scaler

  score_device(entity_id: str, device_class: str) → PredictiveResult
    - Fetches last 24hr telemetry from TBClient (hourly resolution)
    - Extracts and scales features into sequence tensor
    - Runs LSTM inference
    - Returns: { failure_probability (float), 
                 predicted_failure_window (str: "24hr" | "48hr" | "72hr"),
                 contributing_features (dict),
                 confidence (float) }

  generate_work_order_data(entity_id, result: PredictiveResult) → dict
    - Returns structured work order data based on device_class and failure signature
    - Includes: recommended parts (device-class-specific), 
                skill_level, estimated_labour_hours, safety_prerequisites

LSTM_FAILURE_THRESHOLD from env (default 0.75).
Use PyTorch. Save/load with torch.save/torch.load.
```

---

### Task 6.2 — Daily batch job

**Prompt for AI:**
```
Write fastapi/services/predictive_batch.py — a scheduled job that runs daily.

Schedule: APScheduler AsyncIOScheduler, cron at hour=LSTM_BATCH_HOUR (from env, default 2)

Job steps:
1. Query TBClient for all registered BMS devices
2. For each device: call LSTMPredictiveService.score_device(entity_id, device_class)
3. Write score to equipment_health table (TimescaleDB hypertable)
4. If failure_probability > LSTM_FAILURE_THRESHOLD:
   a. Check Redis: has a predictive alarm already been created for this device 
      in the last 48hrs? (key: pred_alarm:{entity_id}, TTL 48hrs) — skip if yes
   b. Create PREDICTIVE_FAILURE alarm in ThingsBoard via TBClient.create_alarm():
      { type: PREDICTIVE_FAILURE, severity: WARNING, 
        details: { failure_probability, predicted_window, contributing_features } }
   c. Create work order in PostgreSQL via work order service
   d. Set Redis key to prevent duplicate alarms

Register the scheduler in FastAPI lifespan (startup/shutdown).
Log: devices scored, failures predicted, alarms created, work orders generated.
```

---

### Checkpoint — Day 16 end

```
✓ APScheduler batch job registered and fires at configured hour
✓ Force-run the batch job manually: trigger it via a test endpoint POST /debug/run-predictive
✓ Equipment health scores written to TimescaleDB for all test devices
✓ Device with simulated bearing wear scores failure_probability > 0.75
✓ PREDICTIVE_FAILURE alarm appears in ThingsBoard alarm feed for that device
✓ Work order created in PostgreSQL with parts list and labour estimate
✓ Work order visible in Work Order widget on the device dashboard
✓ Redis dedup prevents second alarm within 48hr window (run batch twice, verify one alarm)
```

---

---

# Phase 7 — GNN Root Cause Analysis
## Day 17

**Goal:** When multiple alarms cascade, the GNN identifies the single root cause device and writes it back to all cascade alarms in ThingsBoard within 8 seconds.

---

### Task 7.1 — Topology graph builder

**Prompt for AI:**
```
Write fastapi/services/topology.py with:

Class TopologyGraph:
  Wraps a NetworkX DiGraph representing the device estate.

  build_from_tb() → None
    - Queries TBClient for all devices and their relations
    - Nodes: each device (entity_id, device_class, location)
    - Edges encode relationships (types: power_dependency, network_adjacency, 
      hvac_zone, handover)
    - Saves graph to disk: models/topology.gpickle

  load() → DiGraph

  get_subgraph(entity_ids: list[str], hops: int = 2) → DiGraph
    - Returns subgraph containing all input nodes + neighbours within N hops

The graph is rebuilt nightly (add to APScheduler) and on-demand via 
POST /debug/rebuild-topology.
```

---

### Task 7.2 — GNN model

**Prompt for AI:**
```
Write fastapi/services/gnn.py with:

Class GNNRootCauseService:

  The GNN model: a 2-layer Graph Convolutional Network (PyTorch Geometric)
  Node features: [ device_class_embedding (8-dim), 
                   recent_alarm_count (last 60s),
                   current_anomaly_score, 
                   is_in_cascade (bool) ]
  Output: probability that each node is the root cause

  train(topology: DiGraph, historical_cascades: list[dict]) → None
    - historical_cascades: list of { alarm_ids, root_cause_entity_id }
    - Trains GCN to identify root cause nodes
    - Saves model: models/gnn_rootcause.pth

  find_root_cause(alarm_entity_ids: list[str]) → RootCauseResult
    - Builds subgraph from alarm entities + 2-hop neighbours
    - Enriches node features from live anomaly_scores and Redis alarm counts
    - Runs GCN inference
    - Returns: { root_cause_entity_id, root_cause_device_name,
                 confidence (float), explanation (str),
                 blast_radius: list[entity_id] }
    - explanation: plain English, e.g. "Core switch SW-B2-01 failure 
      caused downstream outages in 11 connected devices across floors 2-4"
    - Must complete in under 8 seconds

For MVP: if no trained GNN model exists, fall back to a heuristic — 
the device with the highest anomaly_score in the cascade subgraph is the root cause.
```

---

### Task 7.3 — Cascade webhook handler

**Prompt for AI:**
```
Update the POST /webhook/cascade handler in fastapi/routers/webhook.py:

On receiving cascade payload { alarm_ids, entity_ids, ts }:
1. Load topology subgraph for the cascade entity_ids (2-hop neighbourhood)
2. Call GNNRootCauseService.find_root_cause(entity_ids)
3. For each alarm_id in alarm_ids:
   Write to ThingsBoard via TBClient.update_alarm_attributes(alarm_id, {
     root_cause_entity_id: result.root_cause_entity_id,
     root_cause_device_name: result.root_cause_device_name,
     cascade_explanation: result.explanation,
     gnn_confidence: result.confidence,
     blast_radius_count: len(result.blast_radius)
   })
4. Log full result to audit_log

Total processing time target: under 8 seconds from webhook receipt to TB write.
Add timing instrumentation and log the duration.
```

---

### Checkpoint — Day 17 end

```
✓ Topology graph built from ThingsBoard device relations (verify node + edge counts)
✓ POST /webhook/cascade processes test payload and returns within 8 seconds
✓ All cascade alarms in ThingsBoard show root_cause_device_name attribute
✓ cascade_explanation is plain English and identifies the root device correctly
✓ Heuristic fallback works when GNN model file does not exist
✓ audit_log contains full cascade trace with timing
```

---

---

# Phase 8 — Demo Simulator & Hardening
## Days 18–19

**Goal:** Three fully scripted fault scenarios injectable via a single REST call. Demo runs without any manual intervention. System handles 10k events/min.

---

### Task 8.1 — MQTT device simulator

**Prompt for AI:**
```
Write simulator/mqtt_sim.py — a Python service that publishes realistic 
device telemetry to the MQTT broker continuously.

Simulates these devices (configurable via simulator/devices.json):
  - 5 HVAC units (AHU-1A through AHU-3B)
  - 3 energy meters (EM-Floor1, EM-Floor2, EM-Floor3)
  - 4 network switches (SW-Core, SW-B1, SW-B2, SW-B3)
  - 2 BTS base stations (BTS-North, BTS-South)
  - 1 UPS unit (UPS-Main)
  - 1 fire panel (FIRE-Main)

Each device publishes on a realistic schedule:
  HVAC: every 30 seconds
  Energy meters: every 60 seconds
  Network: every 10 seconds
  BTS: every 15 seconds
  UPS/Fire: every 120 seconds

Normal telemetry generated from per-device statistical models 
(mean, std, daily seasonality curve).

MQTT topic per device: v1/devices/me/telemetry (ThingsBoard standard)
Use device access tokens from credentials.csv (output of Task 1.2).
Use paho-mqtt async client.
```

---

### Task 8.2 — Fault injection API

**Prompt for AI:**
```
Write simulator/fault_injector.py — a FastAPI app (port 8001) with a 
REST API for triggering demo fault scenarios.

POST /inject/{scenario_name}
  Loads scenarios/hvac_bearing_wear.json | nms_cascade.json | motor_prefailure.json
  Overrides normal telemetry for specified devices with fault profile
  Returns { scenario, devices_affected, duration_seconds, started_at }

GET /status
  Returns active scenarios and their progress

POST /reset
  Clears all active fault injections, returns to normal telemetry

Scenario JSON format (write all three files):

hvac_bearing_wear.json:
  Target: AHU-3B
  Duration: 8 minutes
  Profile: power_consumption drifts from normal to +23% over 4 minutes,
           then holds. motor_vibration_rms gradually increases.
  Expected result: Anomaly detected at ~3 minutes, Chat-to-Fix resolves in 90s.

nms_cascade.json:
  Target: SW-Core (the core switch)
  Duration: 5 minutes  
  Profile: SW-Core error_rate spikes to 100%, rx_bytes drops to 0.
           After 15 seconds: SW-B1, SW-B2, SW-B3 also show packet_loss=100%.
           After 30 seconds: BTS-North and BTS-South show connectivity loss.
  Expected result: 6 cascade alarms → GNN identifies SW-Core as root cause in 8s.

motor_prefailure.json:
  Target: AHU-2C (an elevator motor)
  Duration: 36 hours (simulated — compress to 3 minutes for demo)
  Profile: vibration_rms gradually increases from 2.1 to 8.4 mm/s,
           current_draw increases from 4.2A to 6.8A
  Expected result: LSTM batch job (force-triggered) creates PREDICTIVE_FAILURE alarm.
```

---

### Task 8.3 — Load testing

**Prompt for AI:**
```
Write a Locust load test file locustfile.py that tests the system at 10,000 
telemetry events per minute:

Tasks:
1. Publish MQTT telemetry to ThingsBoard (use paho-mqtt in Locust task)
2. GET /health — verify FastAPI is responding
3. POST /chat — with a pre-defined question for a test entity_id
4. GET /workorders?entity_id=test-device

Target: 
  - 10,000 MQTT events/min sustained for 5 minutes
  - Chat endpoint p95 latency < 90 seconds
  - Webhook endpoint p95 latency < 500ms
  - Zero 5xx errors during load test

Assert these in a custom Locust event listener and print pass/fail summary.
```

---

### Task 8.4 — Demo script

Write this out fully — the exact sequence for the pitch demo.

```
DEMO SCRIPT — Platform 2 IoT Operations Intelligence
Total runtime: ~8 minutes

SETUP (before audience arrives):
  docker compose up -d
  python simulator/mqtt_sim.py &
  Open ThingsBoard UI at http://localhost:8080
  Navigate to "Head Office Building" dashboard — live telemetry visible on all devices
  Open AHU-3B device dashboard — Chat-to-Fix widget visible

--- SCENARIO 1: Chat-to-Fix (4 minutes) ---

[0:00] Show ThingsBoard dashboard — all devices green, live telemetry streaming
  Point out: "This is the live device console — no custom UI built by us"

[0:30] Trigger fault: POST http://localhost:8001/inject/hvac_bearing_wear
  Watch AHU-3B power consumption rising on the energy chart

[2:00] Anomaly alarm fires in ThingsBoard alarm feed
  Click the alarm — show ai_anomaly_score and ai_explanation attributes
  "The AI has already scored this as a genuine anomaly — 3.8 sigma above baseline"

[2:30] Click Chat-to-Fix widget on AHU-3B dashboard
  Type: "Why is HVAC floor 3 consuming 23% more power and what should I do?"
  Hit send

[3:30] LLM response streams in — specific root cause, interim fix, parts, work order
  "That was 60 seconds. A manual investigation would take 40-60 minutes."

[4:00] Show work order created in Work Order widget
  "Parts ordered, technician assigned, interim fix applied."

--- SCENARIO 2: GNN Cascade (2 minutes) ---

[4:00] Trigger: POST http://localhost:8001/inject/nms_cascade
  Watch alarm feed — 6 alarms fire in 30 seconds

[4:45] Click any cascade alarm — show root_cause_device_name = SW-Core
  cascade_explanation is visible
  "The GNN traced 6 cascade alarms to a single root cause in 8 seconds.
   A NOC engineer would spend 30-60 minutes correlating these manually."

--- SCENARIO 3: Predictive Maintenance (2 minutes) ---

[6:00] Trigger: POST http://localhost:8001/inject/motor_prefailure
  Trigger: POST http://localhost:8000/debug/run-predictive

[6:30] PREDICTIVE_FAILURE alarm appears — 36 hours ahead of simulated failure
  Open Work Order widget: parts list, safety prerequisites, maintenance window

[7:30] "No unplanned downtime. Parts ordered before the failure occurred."

[8:00] Close
```

---

### Checkpoint — Day 19 end

```
✓ MQTT simulator running — all 16 devices publishing live telemetry to ThingsBoard
✓ POST /inject/hvac_bearing_wear triggers anomaly within 3 minutes
✓ POST /inject/nms_cascade triggers 6 cascade alarms, GNN resolves in <8 seconds
✓ POST /inject/motor_prefailure + debug batch trigger creates PREDICTIVE_FAILURE alarm
✓ Chat-to-Fix responds in under 90 seconds for demo question
✓ Load test: 10k events/min sustained for 5 minutes, zero 5xx errors
✓ Full demo script run-through timed and under 8 minutes
✓ docker compose up -d starts entire stack cleanly on a fresh machine (test this)
```

---

---

# Phase 9 — Packaging & Pitch Rehearsal
## Day 20

---

### Task 9.1 — Production docker-compose

**Prompt for AI:**
```
Update docker-compose.yml for production/customer deployment:

Changes from dev:
1. Remove simulator service (or mark with profile: demo)
2. Add resource limits on all services (CPU + memory caps)
3. Add named volumes with backup labels
4. ThingsBoard data volume mounted to /opt/platform2/tb-data
5. PostgreSQL data volume mounted to /opt/platform2/pg-data
6. Chroma persist directory mounted to /opt/platform2/chroma-data
7. All secrets via .env file (not hardcoded)
8. Add a platform2-nginx service (nginx:alpine) as reverse proxy:
   - /      → ThingsBoard :8080
   - /api   → FastAPI :8000
   - /sim   → Simulator :8001 (disable in production profile)
   SSL termination ready (commented out, with instructions)

Write a Makefile with targets:
  make start       → docker compose up -d
  make stop        → docker compose down
  make logs        → docker compose logs -f fastapi
  make backup      → tar all named volumes to /opt/platform2/backups/
  make seed        → python knowledge_base/seed.py --dir ./docs
  make train       → python scripts/train_anomaly.py && python scripts/train_lstm.py
  make demo        → docker compose --profile demo up -d
```

---

### Task 9.2 — Onboarding runbook

**Prompt for AI:**
```
Write a CUSTOMER_ONBOARDING.md document that a non-developer can follow 
to deploy Platform 2 for a new customer organisation.

Sections:
1. Server requirements (exact specs, OS, ports to open)
2. Installation (clone repo, copy .env.example to .env, fill in values)
3. First start (make start, verify all services healthy)
4. Device registration (how to prepare the CSV, run onboard_devices.py)
5. Knowledge base seeding (where to put device manuals, how to run seed.py)
6. Baseline training (run train_anomaly.py after 7 days of live data)
7. Dashboard setup (how to add Chat-to-Fix and Work Order widgets to TB dashboards)
8. Operator training checklist (8 things to show operators in the 2-hour handover)
9. Troubleshooting (top 10 issues and fixes)

Write it in plain English — the audience is a customer IT manager, not a developer.
```

---

### Checkpoint — Day 20 end

```
✓ make start on a clean Ubuntu 22.04 VM starts entire stack successfully
✓ make demo adds simulator service and all 3 fault scenarios work
✓ make backup produces a tar archive of all data volumes
✓ Full demo script rehearsed — all 3 scenarios work first time, every time
✓ CUSTOMER_ONBOARDING.md reviewed — no developer jargon, steps are clear
✓ .env.example has every required variable with sensible defaults and comments
✓ All Python dependencies pinned in requirements.txt (no floating versions)
✓ README.md written: what the platform does, quick start, architecture diagram
```

---

---

## Appendix A — ThingsBoard REST API Reference

Key endpoints used by FastAPI. All require JWT Bearer token.

| Method | Endpoint | Used for |
|---|---|---|
| POST | `/api/auth/login` | Get JWT token |
| GET | `/api/device/{deviceId}` | Device metadata |
| GET | `/api/plugins/telemetry/DEVICE/{id}/values/timeseries` | Historical telemetry |
| GET | `/api/plugins/telemetry/DEVICE/{id}/values/attributes` | Device attributes |
| POST | `/api/plugins/telemetry/DEVICE/{id}/attributes/SHARED_SCOPE` | Set device attributes |
| GET | `/api/alarm/DEVICE/{id}?pageSize=10` | Device alarms |
| POST | `/api/alarms` | Create new alarm |
| POST | `/api/alarm/{id}/ack` | Acknowledge alarm |
| POST | `/api/plugins/telemetry/DEVICE/{id}/attributes/SERVER_SCOPE` | Write AI enrichment attributes |

---

## Appendix B — Kafka Topic Schema

All topics publish JSON with this envelope:

```json
{
  "ts": 1714800000000,
  "device_id": "uuid-string",
  "device_class": "hvac",
  "device_name": "AHU-3B",
  "location": "Floor 3 East",
  "telemetry": {
    "temperature": 22.4,
    "power_consumption": 4.8,
    "fan_speed": 1200
  }
}
```

---

## Appendix C — AI Prompt Templates

### Chat-to-Fix system prompt structure

```
You are an expert field operations engineer specialising in [device_class] systems.

DEVICE CONTEXT:
Device: {device_name} | Class: {device_class} | Location: {location}
Current readings: {latest_telemetry}
48hr trends: {telemetry_summary}
Recent alarms: {recent_alarms}

RETRIEVED KNOWLEDGE:
[1] {doc_1_content} (Source: {doc_1_source})
[2] {doc_2_content} (Source: {doc_2_source})
... (up to 5 documents)

INSTRUCTIONS:
Answer only from the context provided above.
Always be specific — include exact values, part numbers, and time estimates.
Structure your response as: Root cause / Immediate action / Permanent fix / Parts / Time.
If a work order is needed, end with a ```work_order JSON block.
If you cannot answer from the context, say so and specify what information is missing.
```

---

## Appendix D — Minimum Server Spec

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 8 vCPU | 16 vCPU |
| RAM | 16 GB | 32 GB |
| Storage | 500 GB SSD | 1 TB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Docker | Engine 24+ | Engine 24+ |
| GPU | Not required | NVIDIA 8GB VRAM (Ollama only) |
| Ports inbound | 80, 443, 1883 (MQTT), 161 (SNMP) | — |
| Ports outbound | LLM API endpoint (if cloud LLM) | — |

---

## Appendix E — Glossary

| Term | Meaning |
|---|---|
| BMS | Building Management System — controls HVAC, lighting, access, fire |
| NMS | Network Management System — monitors routers, switches, BTS, servers |
| RAG | Retrieval-Augmented Generation — LLM answers grounded in retrieved documents |
| SSE | Server-Sent Events — HTTP streaming protocol used for LLM token delivery |
| GNN | Graph Neural Network — AI model operating on network topology graphs |
| LSTM | Long Short-Term Memory — recurrent neural network for time-series prediction |
| Chroma | Open-source vector database for RAG document storage |
| TB | ThingsBoard — open-source IoT platform (used for device management and UI) |
| entity_id | ThingsBoard's UUID identifier for a device |
| PREDICTIVE_FAILURE | Custom alarm type created by LSTM batch job before a failure occurs |
