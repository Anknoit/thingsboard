# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
# Whats already built
## Build Commands

### Backend (Maven)

```bash
# Fast build — skip tests and packaging (use for development iterations)
mvn clean install -T6 -DskipTests -Dpkg.skip=true

# Full build including packaging (DEB, RPM, ZIP, boot JAR)
mvn clean install

# Run a single test class
mvn test -pl application -Dtest=MyTestClass

# Run tests for a specific package
mvn test -pl application -Dtest='org.thingsboard.server.controller.**'
```

### Frontend (Angular)

```bash
cd ui-ngx
npm install
npm start        # Dev server with hot reload, proxies to backend at localhost:8080
npm run build:prod  # Production build
npm run lint        # ESLint
```

### Protobuf

```bash
./build_proto.sh   # Recompile protobuf definitions for transport packages
```

## Running Tests in Parallel (see TEST_FAST.md for full details)

```bash
export MAVEN_OPTS="-Xmx1024m"
export NODE_OPTIONS="--max_old_space_size=4096"
export SUREFIRE_JAVA_OPTS="-Xmx1200m -Xss256k -XX:+ExitOnOutOfMemoryError"

# Step 1: compile everything
mvn clean install -T6 -DskipTests -Dpkg.skip=true

# Step 2: run non-application tests
mvn test -pl='!application,!dao,!ui-ngx,!msa/js-executor,!msa/web-ui' -T4
mvn test -pl dao -Dparallel=packages -DforkCount=4

# Step 3: run application tests by package group (each line is independent)
mvn test -pl application -Dtest='!**/nosql/**,org.thingsboard.server.controller.**' -DforkCount=6 -Dparallel=classes  -Dsurefire.rerunFailingTestsCount=2
mvn test -pl application -Dtest='!**/nosql/**,org.thingsboard.server.edge.**'       -DforkCount=4 -Dparallel=packages -Dsurefire.rerunFailingTestsCount=2
mvn test -pl application -Dtest='!**/nosql/**,org.thingsboard.server.service.**'    -DforkCount=6 -Dparallel=packages -Dsurefire.rerunFailingTestsCount=2
```

### Testcontainers / Docker API Compatibility

If tests fail due to Docker API version mismatch, add to `/etc/docker/daemon.json` and restart Docker:
```json
{ "min-api-version": "1.32" }
```

If Testcontainers can't find Docker: `rm ~/.testcontainers.properties`

### Packaging Flags

| Flag | Skips |
|------|-------|
| `-Dpkg.skip=true` | All packaging (boot JAR + DEB + RPM + ZIP) |
| `-Dpkg.skip.bootjar=true` | Spring Boot fat JAR only |
| `-Dpkg.skip.deb=true` | Debian package only |
| `-Dpkg.skip.rpm=true` | RPM only |
| `-Dpkg.skip.zip=true` | Windows ZIP only |

## Architecture Overview

ThingsBoard is an enterprise IoT platform. The codebase is a multi-module Maven project with an Angular frontend.

### Module Map

```
thingsboard/
├── application/          # Main Spring Boot app (ThingsboardServerApplication)
├── common/               # Shared library modules (actor system, DAO API, queue API,
│                         #   cache, cluster API, transport abstractions, edge API,
│                         #   version control, security, stats, message types, etc.)
├── dao/                  # DAO implementations (PostgreSQL, Cassandra, MongoDB)
├── rule-engine/
│   ├── rule-engine-api/           # Rule node interfaces and models
│   └── rule-engine-components/    # Built-in rule node implementations
├── transport/            # Device-facing protocol servers
│   ├── mqtt/             # MQTT 3.1.1 / 5.0 (custom Netty stack)
│   ├── http/
│   ├── coap/             # Californium-based CoAP/CoAPS
│   ├── lwm2m/            # Leshan-based LwM2M
│   └── snmp/
├── netty-mqtt/           # Custom low-level Netty MQTT codec (shared by transport and client)
├── msa/                  # Microservices packaging for Docker/K8s deployments
│   ├── tb-node/          # ThingsBoard core node image
│   ├── js-executor/      # Sandboxed JS rule chain executor (Node.js)
│   ├── web-ui/           # Nginx-wrapped Angular UI image
│   └── vc-executor/      # Version-control executor
├── ui-ngx/               # Angular 20 frontend SPA
├── rest-client/          # Java REST client library for TB API
├── monitoring/           # Prometheus/Grafana monitoring support
├── tools/                # CLI utilities
└── docker/               # Docker Compose files for local infra
```

### Key Architectural Concepts

**Actor System** (`common/actor`): ThingsBoard uses a custom actor framework (not Akka) for concurrent, message-driven processing. Device sessions, rule chains, and tenant contexts each run as actors.

**DAO Abstraction** (`common/dao-api` + `dao/`): The DAO layer is database-agnostic. The `dao` module provides implementations for PostgreSQL (JPA/JDBC), Cassandra, and MongoDB. Runtime choice is via configuration.

**Transport Layer**: Each protocol (MQTT, CoAP, HTTP, LwM2M, SNMP) is a separate Spring Boot module that communicates with the core via gRPC and the internal queue. Transports can be deployed as separate services (MSA mode) or embedded in the monolith.

**Rule Engine**: Visual, node-graph processing pipeline. Rule nodes are Spring beans implementing `TbNode`. JavaScript nodes run in the sandboxed `js-executor` service (Node.js + vm2). The `rule-engine-components` module contains all built-in node types.

**Queue Abstraction** (`common/queue`): Kafka, RabbitMQ, and AWS SQS are supported interchangeably. The queue is the integration point between transports and the core when running in MSA mode.

**Cluster / gRPC** (`common/cluster-api`): Nodes discover each other via ZooKeeper (Apache Curator). Inter-node calls use gRPC with Protobuf. Partition-based entity ownership determines which node handles a given device/tenant.

**Frontend** (`ui-ngx`): Angular 20 + NgRx + Angular Material + TailwindCSS. Real-time updates use WebSocket subscriptions. The dashboard/widget system is the most complex part — widgets are dynamically compiled Angular components.

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Java | 25 |
| Spring Boot | 3.5.13 |
| gRPC / Protobuf | 1.76.0 / 3.25.5 |
| MQTT | Custom Netty codec + Paho |
| CoAP | Californium 3.12.1 |
| LwM2M | Leshan 2.0.0-M15 |
| Databases | PostgreSQL, MongoDB, Cassandra |
| Cache | Valkey/Redis (Sentinel or Cluster) |
| Message Queue | Kafka, RabbitMQ, AWS SQS |
| Cluster | ZooKeeper + Apache Curator 5.6.0 |
| Frontend | Angular 20, NgRx, RxJS 7, Material, Tailwind |
| Expression lang | TBEL 1.2.9 (ThingsBoard Expression Language) |

### Main Configuration

`application/src/main/resources/thingsboard.yml` is the authoritative runtime config (~150 KB). Every property supports environment variable override (e.g., `${HTTP_BIND_PORT:8080}`). Docker Compose files in `docker/` set these env vars for local infrastructure stacks.

### Deployment Modes

- **Monolith**: Single `ThingsboardServerApplication` JVM. All transports embedded. Default for development.
- **MSA**: Separate Docker containers for `tb-node`, `js-executor`, `web-ui`, `vc-executor`, transports. Coordinated via Kafka + ZooKeeper. Configured via the `msa/` module and Docker Compose.




# What we are developing
# CLAUDE.md — NavNet Development Instructions

> This file governs all AI-assisted development for **NavNet** — Tasaar's IoT Operations
> Intelligence Platform. Every response, every file generated, every decision made must follow
> the rules in this document without exception. Read this file completely before touching any code.

---

## 1. Product Identity

| Attribute | Value |
|---|---|
| **Product name** | NavNet |
| **Company** | Tasaar |
| **Full name (formal)** | Tasaar NavNet |
| **tagline** | *See everything. Fix anything.* |
| **Internal codename** | platform2 (repository / Docker / env vars only) |

### Naming rules — enforced everywhere

- The user-facing product is always called **NavNet** — never the underlying registry platform name, never "the IoT platform", never "Platform 2"
- The device registry platform is an **internal implementation detail**. It is never referenced in:
  - Any UI text, widget labels, or dashboard titles
  - Documentation delivered to customers
  - Error messages visible to operators
  - API response bodies
  - Log lines that could surface in a UI
- The two custom widgets are **NavNet Chat** and **NavNet WorkOrders** — never "custom widget" or "Chat-to-Fix widget"
- The AI Chat feature is called **NavNet Chat** in all user-facing text
- Work order feature is called **NavNet WorkOrders**
- The AI enrichment on alarms is called **NavNet Intelligence**

---

## 2. Technology Stack

Never suggest alternatives to these. Never upgrade major versions without explicit instruction.

### Backend
| Layer | Technology | Version |
|---|---|---|
| API framework | FastAPI | `^0.111` |
| Python | CPython | `3.11` |
| ASGI server | Uvicorn | `^0.29` |
| HTTP client | httpx | `^0.27` (async) |
| Database ORM | SQLAlchemy | `^2.0` (async) |
| Migrations | Alembic | `^1.13` |
| Validation | Pydantic v2 | `^2.7` |
| Settings | pydantic-settings | `^2.2` |
| Task queue | APScheduler | `^3.10` (AsyncIOScheduler) |
| Message bus | aiokafka | `^0.10` |
| Cache | redis-py | `^5.0` (async) |
| Logging | structlog | `^24.1` |
| Testing | pytest + pytest-asyncio | `^8.x` |

### AI / ML
| Layer | Technology |
|---|---|
| RAG orchestration | LangChain (`langchain`, `langchain-community`, `langchain-chroma`) |
| Vector store | ChromaDB |
| Anomaly detection | scikit-learn (Isolation Forest) |
| Predictive model | PyTorch (`^2.2`) |
| Graph model | PyTorch Geometric |
| LLM — Claude | `anthropic` SDK, model `claude-sonnet-4-20250514` |
| LLM — OpenAI | `openai` SDK, model `gpt-4o` |
| LLM — self-hosted | Ollama REST API, model `llama3` |

### Infrastructure
| Service | Image |
|---|---|
| Device registry | `thingsboard/tb-postgres` (internal — branded as NavNet) |
| Message bus | `confluentinc/cp-kafka` |
| Primary database | `timescale/timescaledb` |
| Cache | `redis:alpine` |
| Vector store | `chromadb/chroma` |
| Reverse proxy | `nginx:alpine` |

### Widgets
- Vanilla HTML + JavaScript only — no framework, no npm, no build step
- Pasted directly into NavNet widget editor
- Must match NavNet Material Design aesthetic

---

## 3. Project Structure

Maintain this structure exactly. Do not create files outside it without instruction.

```
vantage-nms/
├── CLAUDE.md                        ← this file
├── README.md
├── CUSTOMER_ONBOARDING.md
├── Makefile
├── docker-compose.yml               ← full stack
├── docker-compose.override.yml      ← demo/dev overrides
├── .env.example
├── .gitignore
│
├── fastapi/
│   ├── Dockerfile
│   ├── requirements.txt             ← all deps pinned to exact versions
│   ├── main.py
│   ├── config.py                    ← pydantic-settings BaseSettings
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── chat.py                  ← NavNet Chat SSE endpoint
│   │   ├── webhook.py               ← alarm enrichment + cascade trigger
│   │   ├── workorders.py            ← NavNet WorkOrders CRUD
│   │   └── health.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_adapter.py           ← provider-agnostic LLM interface
│   │   ├── rag.py                   ← LangChain RAG pipeline
│   │   ├── context_builder.py       ← device context assembly
│   │   ├── prompt_builder.py        ← system prompt construction
│   │   ├── anomaly.py               ← Isolation Forest service
│   │   ├── predictive.py            ← LSTM service + batch job
│   │   ├── gnn.py                   ← GNN root cause service
│   │   ├── topology.py              ← NetworkX topology graph
│   │   └── registry_client.py             ← NavNet Registry API wrapper
│   ├── consumers/
│   │   ├── __init__.py
│   │   └── telemetry.py             ← Kafka consumer → anomaly scorer
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py               ← all Pydantic models
│   ├── db/
│   │   ├── __init__.py
│   │   ├── postgres.py              ← SQLAlchemy async engine + session
│   │   └── migrations/
│   │       ├── env.py
│   │       └── versions/
│   └── tests/
│       ├── conftest.py
│       ├── test_chat.py
│       ├── test_webhook.py
│       ├── test_anomaly.py
│       ├── test_predictive.py
│       └── test_gnn.py
│
├── widgets/
│   ├── navnet_chat.html            ← NavNet Chat widget
│   └── navnet_workorders.html      ← NavNet WorkOrders widget
│
├── simulator/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── mqtt_sim.py
│   ├── fault_injector.py
│   ├── devices.json
│   └── scenarios/
│       ├── hvac_bearing_wear.json
│       ├── nms_cascade.json
│       └── motor_prefailure.json
│
├── knowledge_base/
│   ├── seed.py
│   └── docs/                        ← customer device manuals (gitignored)
│
├── scripts/
│   ├── train_anomaly.py
│   ├── train_lstm.py
│   ├── build_topology.py
│   └── onboard_devices.py
│
├── models/                          ← trained model files (gitignored)
│   ├── isolation_forest_hvac.pkl
│   ├── isolation_forest_energy.pkl
│   ├── isolation_forest_network.pkl
│   ├── isolation_forest_infra.pkl
│   ├── lstm_hvac.pth
│   ├── gnn_rootcause.pth
│   └── topology.gpickle
│
└── docs/
    ├── internal/                    ← developer docs (TB references allowed here)
    │   ├── architecture.md
    │   ├── kafka_topics.md
    │   └── registry_integration.md
    └── customer/                    ← customer-facing docs (no TB references)
        └── operator_guide.md
```

---

## 4. Code Standards

### 4.1 Python — universal rules

```python
# ALWAYS
- Type hints on every function signature — parameters and return types
- Docstrings on every class and every public function (Google style)
- Async functions for all I/O — never use synchronous requests, sqlite3, or psycopg2 directly
- Pydantic models for all request/response bodies — no raw dicts in router signatures
- Structured logging via structlog — never use print() or logging.basicConfig()
- Environment variables via config.py Settings only — never os.environ.get() inline
- Exception classes in a dedicated exceptions.py — never raise generic Exception()

# NEVER
- No hardcoded strings for URLs, credentials, model names, or thresholds
- No synchronous blocking calls inside async functions (use asyncio.to_thread() if needed)
- No bare except: clauses — always catch specific exception types
- No mutable default arguments (def f(x=[]) is forbidden)
- No global mutable state outside of the lifespan-managed service singletons
- No TODO comments in committed code — open a GitHub issue instead
```

### 4.2 FastAPI — router rules

```python
# Every router file follows this pattern:
from fastapi import APIRouter, Depends, HTTPException, status
from ..models.schemas import RequestModel, ResponseModel
from ..services.relevant_service import RelevantService
from ..db.postgres import get_db

router = APIRouter(prefix="/resource", tags=["Resource"])

@router.post(
    "/",
    response_model=ResponseModel,
    status_code=status.HTTP_201_CREATED,
    summary="One-line description",
    description="Longer description if needed",
)
async def create_resource(
    body: RequestModel,
    db: AsyncSession = Depends(get_db),
) -> ResponseModel:
    """Google-style docstring."""
    ...
```

- All endpoints have `summary` and `response_model`
- HTTP status codes must be explicit (`status.HTTP_200_OK`, not `200`)
- Dependencies via `Depends()` only — never instantiate services inside route functions
- Return type annotations must match `response_model`
- All 4xx errors use `HTTPException` with a descriptive `detail` string
- All 5xx errors bubble up to the global exception handler — never catch and swallow

### 4.3 Pydantic models

```python
# schemas.py — all models in one file, grouped by domain
# Every model:
- Inherits from BaseModel
- Has a model_config = ConfigDict(str_strip_whitespace=True, frozen=False)
- Has field-level validation via @field_validator where input can be invalid
- Uses explicit Field() with description= for every field (auto-generates OpenAPI docs)
- Request models and Response models are separate classes — never share the same model
- Database row models use a separate ORM-mapped class — never expose SQLAlchemy models directly
```

### 4.4 Service layer rules

```python
# Every service class:
- Is instantiated once in main.py lifespan and stored on app.state
- Is injected into routers via a Depends() factory function
- Has an async def health_check() -> bool method
- Has no direct database calls — uses repository functions from db/postgres.py
- Has no direct HTTP calls — uses registry_client.py for NavNet Registry, llm_adapter.py for LLM
- Raises domain-specific exceptions (VantageAnomalyError, VantageLLMError, etc.)

# Service singleton pattern:
async def get_anomaly_service(request: Request) -> AnomalyService:
    return request.app.state.anomaly_service
```

### 4.5 Error handling

```python
# exceptions.py — all custom exceptions
class VantageError(Exception):
    """Base exception for all NavNet errors."""
    pass

class VantageLLMError(VantageError):
    """LLM provider returned an error or timed out."""
    pass

class VantageDeviceNotFoundError(VantageError):
    """Device entity_id not found in NavNet registry."""
    pass

class VantageRAGError(VantageError):
    """RAG retrieval pipeline failure."""
    pass

class VantageAnomalyModelError(VantageError):
    """Anomaly model not loaded or inference failed."""
    pass

# Global handler in main.py catches VantageError subclasses
# and returns structured JSON: { error, detail, ts, request_id }
```

### 4.6 Logging

```python
# Every module gets its own logger — never pass loggers between modules
import structlog
logger = structlog.get_logger(__name__)

# Every log entry must include:
logger.info(
    "vantage.chat.request",          # event name: product.module.action
    entity_id=entity_id,
    device_class=device_class,
    question_length=len(question),
    request_id=request_id,
)

# Log levels:
# DEBUG  — internal state, variable values (dev only)
# INFO   — business events (request received, model scored, alarm created)
# WARNING — recoverable errors (LLM rate limit, partial context, cache miss)
# ERROR  — failures that affect the operator (LLM failed, DB write failed)
# CRITICAL — system-level failures (Kafka disconnected, DB unreachable)

# Never log: passwords, API keys, full telemetry payloads, PII
```

### 4.7 Testing

```python
# Every service function has a corresponding unit test
# Every router endpoint has an integration test using httpx.AsyncClient
# Minimum coverage: 80% on services/, 100% on models/schemas.py

# Test file pattern:
@pytest.mark.asyncio
async def test_chat_returns_sse_stream_for_valid_device(
    async_client: httpx.AsyncClient,
    mock_registry_client: MagicMock,
    mock_llm_adapter: MagicMock,
):
    """Chat endpoint streams tokens for a valid entity_id and question."""
    ...

# All external calls (NavNet Registry, LLM, Kafka) are mocked in tests
# Use pytest fixtures in conftest.py — never mock inside test functions
# Tests must not require a running database — use SQLite in-memory for unit tests
```

---

## 5. System Design Principles

### 5.1 Separation of concerns

```
Device data ownership:     NavNet Registry (internal)
AI inference ownership:    FastAPI services
UI ownership:              NavNet Registry dashboards + 2 custom widgets
Persistence ownership:     PostgreSQL (work orders, audit, health scores)
                           Chroma (vector embeddings)
                           Redis (ephemeral cache only)
```

- **FastAPI never renders UI** — it is a pure API backend
- **Widgets never contain business logic** — they call FastAPI and render results
- **NavNet Registry never calls AI models directly** — it calls FastAPI webhooks
- **AI services never query NavNet Registry directly** — they use `registry_client.py` only

### 5.2 Async-first

- Every I/O operation is async — database, HTTP, Kafka, file reads for large files
- CPU-bound work (model inference) runs in `asyncio.to_thread()` to avoid blocking the event loop
- Kafka consumer runs as a background task started in FastAPI lifespan
- APScheduler uses `AsyncIOScheduler` — never `BackgroundScheduler`

### 5.3 Idempotency

- Every webhook endpoint is idempotent — duplicate alarm payloads produce the same result
- Redis dedup keys enforce idempotency for alarm enrichment (TTL: 60s) and predictive alarms (TTL: 48hr)
- Work order creation checks for an existing open work order for the same `entity_id` + fault signature before creating a new one
- All database writes use `INSERT ... ON CONFLICT DO NOTHING` or `ON CONFLICT DO UPDATE` — never blindly insert

### 5.4 Resilience

- `registry_client.py` retries all requests 3 times with exponential backoff (1s, 2s, 4s)
- LLM calls have a 120-second timeout — fail fast and return a structured error to the widget
- Kafka consumer catches all processing exceptions per message — failed messages go to `platform2.dlq` dead letter topic, consumer continues
- If Chroma is unavailable, RAG pipeline returns an empty document list and logs a warning — Chat still works with device context only
- If NavNet Registry is unavailable, `context_builder.py` returns partial context with `tb_available: false` flag — Chat still proceeds

### 5.5 Observability

Every AI inference call logs:
```python
{
    "event": "vantage.inference.complete",
    "service": "anomaly|predictive|gnn|chat",
    "entity_id": "...",
    "duration_ms": 142,
    "model_version": "...",
    "result_summary": "...",   # non-sensitive summary only
    "request_id": "uuid"
}
```

The `/health` endpoint returns:
```json
{
  "status": "healthy|degraded|unhealthy",
  "version": "0.1.0",
  "services": {
    "postgres": "ok|error",
    "redis": "ok|error",
    "chroma": "ok|error",
    "kafka": "ok|error",
    "registry": "ok|error",
    "llm": "ok|error"
  },
  "models_loaded": {
    "isolation_forest": ["hvac", "energy", "network", "infra"],
    "lstm": ["hvac"],
    "gnn": true
  }
}
```

### 5.6 Configuration hierarchy

```
1. Environment variables (.env file)      ← highest priority
2. .env.example defaults                  ← documentation only
3. Hardcoded constants in config.py       ← lowest priority, for true constants only
```

Never use `if ENV == "production"` branching in application code. All environment differences are expressed through configuration values.

### 5.7 Data flow — one direction

```
Devices → NavNet Registry → Kafka → FastAPI AI services → NavNet Registry (write-back only)
                     → Webhook → FastAPI AI services → NavNet Registry (write-back only)
                                                     → PostgreSQL
Operator → Widget → FastAPI /chat → LLM → Widget (SSE stream)
                  → FastAPI /workorders → PostgreSQL
```

FastAPI never pushes unsolicited data to the widget. Widgets poll or respond to operator actions only.

---

## 6. Widget Design Standards

Both widgets (`navnet_chat.html`, `navnet_workorders.html`) must follow these rules.

### 6.1 Visual standards

```css
/* Use NavNet CSS variables — never hardcode colours */
--tb-primary-color          /* primary brand colour from TB theme */
--tb-primary-text-color     /* primary text */
--tb-secondary-text-color   /* secondary/muted text */
--tb-background-color       /* widget background */
--tb-card-background-color  /* card surfaces */
--tb-error-color            /* error states */

/* Typography */
font-family: Roboto, sans-serif;   /* always — matches NavNet */
font-size: 14px;                    /* base size for widget body */

/* Spacing — use multiples of 8px: 4, 8, 12, 16, 24, 32 */
/* Border radius: 4px for inputs, 8px for cards */
/* Elevation (box-shadow): match NavNet Material elevation levels */
```

### 6.2 NavNet Chat widget — UI spec

```
┌─────────────────────────────────────────────┐
│ ⬡ NavNet Chat          [device name]  [×] │  ← header bar
├─────────────────────────────────────────────┤
│ [Context pills: Power: 4.8kW | Temp: 22°C] │  ← live telemetry strip
├─────────────────────────────────────────────┤
│                                             │
│  [Response area — scrollable]               │  ← LLM response renders here
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │ Work Order Card (if generated)      │   │  ← structured card
│  │ P2 · AHU-3B · SKF bearing kit (×2) │   │
│  └─────────────────────────────────────┘   │
│                                             │
├─────────────────────────────────────────────┤
│ [Ask about this device...            ] [→] │  ← input + send
│                              Ctrl+Enter     │
└─────────────────────────────────────────────┘

States:
  idle       — input focused, no response
  loading    — typing indicator (3 animated dots), input disabled
  streaming  — tokens appear, input disabled
  complete   — copy button appears, input re-enabled
  error      — error message in red, retry button
```

### 6.3 NavNet WorkOrders widget — UI spec

```
┌─────────────────────────────────────────────┐
│ ⬡ NavNet WorkOrders    [device name]       │
├─────────────────────────────────────────────┤
│ ● P1 · AHU-3B bearing wear         OPEN    │  ← priority badge + status
│   Due: 18 May 2026 · 2hr labour            │
│   [Acknowledge ▾]                          │
├─────────────────────────────────────────────┤
│ ● P3 · AHU-3B predictive check    OPEN    │
│   Due: 22 May 2026 · 1hr labour            │
│   [Acknowledge ▾]                          │
├─────────────────────────────────────────────┤
│ No more open work orders                    │
└─────────────────────────────────────────────┘

Priority colours:
  P1 — #D32F2F (red)
  P2 — #E64A19 (deep orange)
  P3 — #F57C00 (orange)
  P4 — #1976D2 (blue)
  P5 — #616161 (grey)

Overdue work orders: due date text turns red, card gets left border #D32F2F
```

### 6.4 Widget code rules

```javascript
// ALWAYS
- All FASTAPI_URL, entity_id, and config read from self.ctx at widget init — never hardcoded
- SSE parsed with fetch() + ReadableStream — never EventSource (EventSource doesn't support POST)
- All API calls wrapped in try/catch with user-visible error states
- Auto-refresh using setInterval() — always clearInterval() on widget destroy
- Widget registers a destroy callback: self.onDestroy = () => { clearInterval(refreshInterval) }

// NEVER
- No external JS libraries (no jQuery, no axios, no lodash)
- No external CSS (no Bootstrap, no Tailwind CDN)
- No localStorage or sessionStorage
- No console.log() in production widget code
- No hardcoded IP addresses or ports
```

---

## 7. API Design Standards

### 7.1 URL structure

```
/health                              GET
/chat                                POST   ← SSE stream
/webhook/alarm                       POST   ← NavNet Registry rule chain call
/webhook/cascade                     POST   ← NavNet Registry cascade trigger
/workorders                          GET, POST
/workorders/{id}                     GET
/workorders/{id}/status              PATCH
/debug/run-predictive                POST   ← dev/demo only, guarded by DEBUG=true
/debug/rebuild-topology              POST   ← dev/demo only
```

### 7.2 Response envelope

All non-streaming endpoints return:
```json
{
  "data": { ... },          // the actual payload
  "meta": {
    "request_id": "uuid",
    "ts": "2026-05-07T10:00:00Z",
    "version": "0.1.0"
  }
}
```

All error responses return:
```json
{
  "error": "VantageLLMError",
  "detail": "LLM provider claude timed out after 120s",
  "request_id": "uuid",
  "ts": "2026-05-07T10:00:00Z"
}
```

### 7.3 SSE event format (`/chat`)

```
data: {"type": "token",      "content": "Supply air damper"}
data: {"type": "token",      "content": " actuator AHU-3B"}
data: {"type": "work_order", "id": "uuid", "data": { ... }}
data: {"type": "done",       "duration_ms": 4823}
data: {"type": "error",      "message": "LLM timed out", "code": "LLM_TIMEOUT"}
```

### 7.4 Pagination

All list endpoints support:
```
GET /workorders?entity_id=x&status=open&page=1&page_size=20&sort=priority&order=asc
```

Response includes:
```json
{
  "data": [...],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 47,
    "total_pages": 3
  }
}
```

---

## 8. Database Standards

### 8.1 Schema rules

```sql
-- Every table has:
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()

-- Always use:
TIMESTAMPTZ not TIMESTAMP (timezone-aware everywhere)
TEXT not VARCHAR(n) unless there is a genuine length constraint
JSONB not JSON (indexed, binary)
UUID not SERIAL for primary keys

-- Naming conventions:
Tables:         snake_case plural       (work_orders, audit_logs)
Columns:        snake_case              (entity_id, created_at)
Indexes:        idx_{table}_{column}    (idx_work_orders_entity_id)
Constraints:    fk_{table}_{ref}        (fk_work_orders_entity)
```

### 8.2 Query rules

```python
# ALWAYS use parameterised queries — never string interpolation in SQL
# ALWAYS use async with db.begin() for write transactions
# ALWAYS add indexes for: entity_id, status, created_at on frequently filtered tables
# TimescaleDB hypertables: always chunk_time_interval = INTERVAL '1 day'
# Never SELECT * — always name columns explicitly
```

### 8.3 Migration rules

```bash
# Every schema change gets an Alembic migration
# Migration naming: {number}_{description}.py  e.g. 0001_create_work_orders.py
# Migrations must be reversible — always implement downgrade()
# Never edit a migration that has been applied to production
# Run migrations in docker-compose healthcheck before FastAPI starts
```

---

## 9. Security Standards

### 9.1 Secrets

```bash
# In .env:
SECRET_KEY=              # 64-char random hex — generated with: openssl rand -hex 32
REGISTRY_ADMIN_PASSWORD=       # never "admin" or "changeme" in production
ANTHROPIC_API_KEY=       # never committed to git

# .gitignore must include:
.env
models/
knowledge_base/docs/
```

### 9.2 Input validation

```python
# All user inputs validated by Pydantic before reaching service layer
# entity_id: UUID format validated — reject anything else
# question: max 1000 characters, stripped of null bytes
# file paths: never accepted from API input — internal use only
# Webhook payloads from NavNet Registry: validate against strict Pydantic schema — reject if invalid
```

### 9.3 Rate limiting

```python
# /chat endpoint: 10 requests per minute per entity_id (Redis sliding window)
# /webhook/alarm: 1000 requests per minute total (Redis counter)
# /webhook/cascade: 100 requests per minute total
# All rate limits configurable via env vars — never hardcoded
# Rate limit response: HTTP 429 with Retry-After header
```

### 9.4 API keys

```python
# All outbound API calls (NavNet Registry, LLM providers):
# - Keys loaded from config only
# - Never logged, even at DEBUG level
# - Redacted in all error messages and stack traces
```

---

## 10. Git & Commit Standards

### 10.1 Branch naming

```
feature/{short-description}      feature/vantage-chat-widget
fix/{short-description}          fix/kafka-consumer-reconnect
chore/{short-description}        chore/pin-dependencies
```

### 10.2 Commit messages

Follow Conventional Commits:
```
feat(chat): add work order card rendering to NavNet Chat widget
fix(anomaly): prevent duplicate alarm enrichment via Redis dedup
chore(deps): pin all requirements to exact versions
docs(internal): add NavNet Registry rule chain export instructions
test(webhook): add cascade endpoint integration tests
refactor(registry_client): extract retry logic to shared decorator
```

### 10.3 What never goes in git

```
.env
*.pkl          (trained models)
*.pth          (PyTorch models)
*.gpickle      (topology graph)
knowledge_base/docs/    (customer PDFs)
models/                 (all trained model files)
```

---

## 11. Requirements File Standards

`fastapi/requirements.txt` — all dependencies pinned to exact versions:

```
# Core
fastapi==0.111.0
uvicorn[standard]==0.29.0
pydantic==2.7.1
pydantic-settings==2.2.1
httpx==0.27.0
structlog==24.1.0

# Database
sqlalchemy[asyncio]==2.0.30
alembic==1.13.1
asyncpg==0.29.0
redis==5.0.4

# Kafka
aiokafka==0.10.0

# Scheduling
apscheduler==3.10.4

# AI / ML
langchain==0.2.0
langchain-community==0.2.0
langchain-chroma==0.1.1
chromadb==0.5.0
scikit-learn==1.4.2
torch==2.2.2
torch-geometric==2.5.3
anthropic==0.26.0
openai==1.26.0

# Utilities
pypdf==4.2.0
networkx==3.3
numpy==1.26.4
pandas==2.2.2

# Testing
pytest==8.2.0
pytest-asyncio==0.23.6
pytest-cov==5.0.0
```

---

## 12. What Claude Must Always Do

When generating any code, documentation, or configuration for this project:

1. **Check naming** — is the underlying registry platform named in a customer-visible context? Rename to "NavNet" immediately.

2. **Check types** — does every function have type hints? Does every Pydantic model have `Field(description=...)`?

3. **Check async** — is every I/O call async? Is any blocking call inside an async function?

4. **Check logging** — does every new function log its start, completion, and any errors using structlog with structured fields?

5. **Check error handling** — does every external call (TB, LLM, Kafka, DB) have specific exception handling with a VantageError subclass?

6. **Check tests** — has a corresponding test been written or noted as required?

7. **Check config** — are all values coming from `config.py` Settings? No inline `os.environ.get()`?

8. **Check the widget** — does any widget code contain logic that belongs in FastAPI? Move it.

9. **Check idempotency** — could this endpoint be called twice for the same event? Add Redis dedup if yes.

10. **Check the response envelope** — does every endpoint return `{ data, meta }` or `{ error, detail, request_id, ts }`?

---

## 13. What Claude Must Never Do

- Never suggest React, Vue, Angular, or any JS framework for the widgets
- Never suggest replacing NavNet Registry with a custom-built device management layer
- Never suggest SaaS, multi-tenancy, or per-device billing features
- Never reference the underlying registry platform name in any customer-visible string, comment in widget code, or customer documentation
- Never use `print()` for debugging — always `logger.debug()`
- Never generate a migration without a corresponding `downgrade()` function
- Never add a new dependency without adding it to `requirements.txt` with a pinned exact version
- Never generate code that catches `Exception` broadly without re-raising or logging with full context
- Never generate synchronous database calls inside async functions
- Never store secrets in code — always in `.env`
- Never suggest upgrading a major version of any dependency in the stack without explicit instruction

---

## 14. Demo Environment

The demo environment is activated with:
```bash
make demo
# equivalent to: docker compose --profile demo up -d
```

This adds the simulator service. In demo mode:

- Fault scenarios are injectable via `POST http://localhost:8001/inject/{scenario}`
- Debug endpoints are active: `/debug/run-predictive`, `/debug/rebuild-topology`
- All three scenarios must complete successfully before any pitch rehearsal

Demo environment must never be used for customer deployments.