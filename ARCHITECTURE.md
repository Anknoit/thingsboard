# ThingsBoard — Comprehensive Architectural Overview

> **Version:** 4.4.0-SNAPSHOT  
> **Generated:** 2026-05-03

---

## Table of Contents

1. [What Is ThingsBoard?](#1-what-is-thingsboard)
2. [Technology Stack](#2-technology-stack)
3. [Repository Layout](#3-repository-layout)
4. [High-Level Architecture Diagram](#4-high-level-architecture-diagram)
5. [Module Deep-Dive](#5-module-deep-dive)
   - 5.1 [Transport Layer](#51-transport-layer)
   - 5.2 [Message Queue (Queue Broker)](#52-message-queue-queue-broker)
   - 5.3 [Core Application Server](#53-core-application-server)
   - 5.4 [Actor System](#54-actor-system)
   - 5.5 [Rule Engine](#55-rule-engine)
   - 5.6 [Data Access Layer (DAO)](#56-data-access-layer-dao)
   - 5.7 [EDQS — Entity Data Query Service](#57-edqs--entity-data-query-service)
   - 5.8 [Web UI (Angular Frontend)](#58-web-ui-angular-frontend)
   - 5.9 [Caching Layer](#59-caching-layer)
   - 5.10 [Cluster Coordination](#510-cluster-coordination)
   - 5.11 [Monitoring](#511-monitoring)
6. [Data Flow Walkthrough](#6-data-flow-walkthrough)
7. [Real-World Example — Smart Cold-Chain Monitoring](#7-real-world-example--smart-cold-chain-monitoring)
8. [Deployment Modes](#8-deployment-modes)
9. [Security Architecture](#9-security-architecture)
10. [Key Configuration Reference](#10-key-configuration-reference)

---

## 1. What Is ThingsBoard?

ThingsBoard is an open-source **IoT platform** that ingests data from millions of devices, processes it in real-time through a visual rule engine, stores it in scalable databases, and serves it through a rich web UI and REST/WebSocket APIs. It supports:

- Multi-protocol device connectivity (MQTT, HTTP, CoAP, LwM2M, SNMP, OPC-UA)
- Multi-tenancy with full data isolation
- A drag-and-drop rule engine for automation and alerting
- Dashboards with live widgets
- Edge computing support (ThingsBoard Edge)
- Horizontal scaling via microservices, Kafka, and ZooKeeper

---

## 2. Technology Stack

| Layer | Technology | Version |
|---|---|---|
| **Language** | Java | 25 |
| **Framework** | Spring Boot | 3.5.13 |
| **Build** | Maven (multi-module) | — |
| **Frontend** | Angular | 20.3.19 |
| **UI Components** | Angular Material | 20.2.14 |
| **State Management** | NgRx | 20.1.0 |
| **Primary DB** | PostgreSQL (JPA/Hibernate) | — |
| **Time-Series DB** | PostgreSQL SQL-TS / TimescaleDB / Apache Cassandra | Cassandra 4.17.0 / 5.0.4 |
| **Message Broker** | Apache Kafka (or in-memory) | — |
| **Cache** | Caffeine (local) / Valkey/Redis (distributed) | Valkey 7.2+ |
| **Service Discovery** | Apache ZooKeeper | 3.9.5 |
| **RPC** | gRPC + Protocol Buffers | gRPC 1.76.0, Protobuf 3.25.5 |
| **MQTT** | Custom Netty-based broker + Eclipse Paho | Paho 1.2.5 |
| **CoAP** | Eclipse Californium | 3.12.1 |
| **LwM2M** | Eclipse Leshan | 2.0.0-M15 |
| **OPC-UA** | Eclipse Milo | 0.6.12 |
| **Security** | JWT (JJWT) + OAuth2 | JJWT 0.12.5 |
| **Serialization** | Protocol Buffers, Jackson JSON | — |
| **Containers** | Docker + Docker Compose | — |
| **Utilities** | Lombok, Guava, Netty | Lombok 1.18.44 |

---

## 3. Repository Layout

```
thingsboard/
│
├── application/          # Main Spring Boot application (REST API, actors, services)
├── common/               # 19 shared sub-libraries
│   ├── actor/            # Actor system interfaces & default implementation
│   ├── message/          # TbMsg, TbMsgMetaData, TbMsgType
│   ├── data/             # DTOs and domain models
│   ├── dao-api/          # DAO interfaces
│   ├── queue/            # Queue abstractions and Kafka/in-memory impls
│   ├── transport/        # Protocol transport abstractions
│   ├── cluster-api/      # Cluster communication interfaces
│   ├── proto/            # Protobuf definitions (generated gRPC stubs)
│   ├── edqs/             # EDQS API
│   ├── edge-api/         # ThingsBoard Edge integration API
│   ├── cache/            # Caffeine / Redis caching abstraction
│   ├── stats/            # Stats collection utilities
│   ├── discovery-api/    # ZooKeeper service discovery
│   ├── coap-server/      # CoAP server abstraction
│   └── util/             # General utilities
│
├── dao/                  # Data Access Layer
│   └── src/main/java/org/thingsboard/server/dao/
│       ├── device/       # Device CRUD (SQL + Cassandra)
│       ├── asset/        # Asset CRUD
│       ├── timeseries/   # Time-series queries
│       ├── sqlts/        # SQL + TimescaleDB time-series impl
│       ├── attributes/   # Attribute storage
│       ├── alarm/        # Alarm management
│       ├── event/        # Event log
│       ├── relation/     # Entity relationship graph
│       ├── sql/          # JPA/Hibernate entities + repositories
│       └── nosql/        # Cassandra implementations
│
├── rule-engine/
│   ├── rule-engine-api/          # TbContext, RuleNode interfaces
│   └── rule-engine-components/   # 30+ node implementations
│       ├── action/     filter/   flow/   transform/
│       ├── telemetry/  metadata/ profile/ math/
│       ├── aws/        gcp/      kafka/  rabbitmq/
│       ├── mqtt/       rest/     mail/   sms/
│       ├── rpc/        delay/    deduplication/
│       ├── geo/        ai/       edge/   debug/
│       └── notification/ transaction/ util/ credentials/
│
├── transport/
│   ├── mqtt/       # MQTT protocol handler (Netty)
│   ├── http/       # HTTP transport (Spring MVC)
│   ├── coap/       # CoAP transport (Californium)
│   ├── lwm2m/      # LwM2M transport (Leshan)
│   └── snmp/       # SNMP transport
│
├── edqs/           # Entity Data Query Service (standalone)
├── netty-mqtt/     # Low-level Netty MQTT codec
├── ui-ngx/         # Angular 20 frontend
├── msa/            # Microservices packaging & Docker configs
│   ├── tb/         # Single-instance image variants
│   ├── tb-node/    # Core node microservice
│   ├── transport/  # Per-protocol transport services
│   ├── js-executor/  # JavaScript rule engine executor
│   ├── vc-executor/  # Version-control executor
│   ├── edqs/       # EDQS microservice
│   ├── web-ui/     # Express.js frontend server
│   └── monitoring/ # Prometheus + Grafana stack
│
├── docker/         # Docker Compose orchestration files
├── monitoring/     # Spring Boot monitoring application
├── rest-client/    # REST SDK for external integrations
├── packaging/      # DEB / RPM / ZIP packaging
└── tools/          # Build utilities
```

---

## 4. High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DEVICES / SENSORS                              │
│       Temp Sensor   Smart Meter   Gateway   Fleet Vehicle   PLC / OPC-UA    │
└──────────┬────────────┬──────────────┬────────────┬───────────────┬─────────┘
           │            │              │            │               │
       MQTT:1883    HTTP:8080      CoAP:5683   LwM2M:5686      SNMP/OPC-UA
           │            │              │            │               │
┌──────────▼────────────▼──────────────▼────────────▼───────────────▼─────────┐
│                          TRANSPORT LAYER                                     │
│   MqttTransportService  HttpTransportService  CoapTransportService           │
│   Lwm2mTransportService  SnmpTransportService                                │
│   (Validate credentials, create session, parse payload, emit TbMsg)          │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │  gRPC / in-process
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MESSAGE QUEUE (Kafka / In-Memory)                   │
│                                                                              │
│  tb_transport.api.requests   tb_rule_engine   tb_core   tb_housekeeper       │
│  tb_transport.notifications  tb_ota_package   tb_usage_stats  edqs.*         │
└──────────────────────┬──────────────────────────────┬───────────────────────┘
                       │                              │
          ┌────────────▼──────────┐      ┌────────────▼──────────────┐
          │   RULE ENGINE SERVICE │      │    CORE APPLICATION        │
          │   (TbRuleEngine)      │      │    (ThingsboardServer)     │
          │                       │      │                            │
          │  Actor System:        │      │  REST API (port 8080)      │
          │  ┌──────────────────┐ │      │  WebSocket subscriptions   │
          │  │  TenantActor     │ │      │  Device state management   │
          │  │  ├─RuleChainActor│ │      │  Alarm service             │
          │  │  │  ├─NodeActor  │ │      │  OTA service               │
          │  │  │  └─NodeActor  │ │      │  API usage tracking        │
          │  │  └─DeviceActor   │ │      │  Job scheduler             │
          │  └──────────────────┘ │      └────────────┬──────────────┘
          └────────────┬──────────┘                   │
                       │                              │
          ┌────────────▼──────────────────────────────▼───────────────┐
          │                    DATA ACCESS LAYER (DAO)                 │
          │                                                            │
          │  ┌─────────────────┐   ┌──────────────────────────────┐   │
          │  │  PostgreSQL      │   │  Cassandra (optional hybrid)  │   │
          │  │  (entities,      │   │  (high-volume time-series)    │   │
          │  │   alarms,        │   └──────────────────────────────┘   │
          │  │   attributes,    │   ┌──────────────────────────────┐   │
          │  │   SQL time-series│   │  TimescaleDB (optional)       │   │
          │  └─────────────────┘   └──────────────────────────────┘   │
          └────────────────────────────────────────────────────────────┘
                       ▲                              ▲
          ┌────────────┴──────────┐      ┌────────────┴──────────────┐
          │   Caffeine / Valkey   │      │   ZooKeeper               │
          │   (Distributed Cache) │      │   (Service Discovery)      │
          └───────────────────────┘      └───────────────────────────┘
                                                      ▲
                               ┌──────────────────────┤
          ┌────────────────────▼──────────────────────▼───────────────┐
          │                    WEB BROWSER / MOBILE APP                │
          │         Angular 20 UI   ←→   REST API + WebSocket          │
          └────────────────────────────────────────────────────────────┘
```

---

## 5. Module Deep-Dive

### 5.1 Transport Layer

The transport layer is the **first point of contact** for devices. Each protocol is a self-contained Spring Boot application (in microservices mode) or an embedded module (in monolith mode).

| Service | Protocol | Port | Library |
|---|---|---|---|
| `MqttTransportService` | MQTT 3.1/3.1.1 | 1883 (TCP), 8883 (TLS) | Custom Netty MQTT codec (`netty-mqtt/`) |
| `HttpTransportService` | HTTP/HTTPS REST | 8080 | Spring MVC |
| `CoapTransportService` | CoAP (UDP) | 5683 | Eclipse Californium |
| `Lwm2mTransportService` | LwM2M (UDP) | 5686 (CoAP+DTLS) | Eclipse Leshan |
| `SnmpTransportService` | SNMP v1/v2c/v3 | 161 | SNMP4J |

**What each transport service does:**

1. **Authenticates the device** — looks up credentials (token, X.509 certificate, or basic auth) against the DAO/cache.
2. **Establishes a session** — creates a `DeviceSessionCtx` and registers it with `SessionMetaData`.
3. **Parses the payload** — converts protocol-specific format (MQTT topic mapping, CoAP URI, HTTP body) into a `TbMsg`.
4. **Forwards to the queue** — publishes the `TbMsg` to the `tb_transport.api.requests` Kafka topic (or in-memory queue) with a gRPC/protobuf envelope.
5. **Handles downlink** — subscribes to `tb_transport.notifications` to receive RPC commands and attribute updates destined for the device.

**MQTT Topic Conventions (default device API):**

```
Publish telemetry:   v1/devices/me/telemetry
Publish attributes:  v1/devices/me/attributes
Subscribe RPC:       v1/devices/me/rpc/request/+
RPC response:        v1/devices/me/rpc/response/{requestId}
Claim device:        v1/devices/me/claim
OTA firmware:        v2/fw/request/{chunkId}/response
```

---

### 5.2 Message Queue (Queue Broker)

The queue is the **nervous system** connecting transports, rule engine, and core services. It supports two backends:

**In-Memory** — suitable for development and single-node deployments. All queues live in JVM heap.

**Apache Kafka** — production-grade, horizontally scalable.

**Core Kafka Topics:**

| Topic | Producers | Consumers | Retention | Partitions |
|---|---|---|---|---|
| `tb_transport.api.requests` | Transport services | Core app | 7 days | 10 |
| `tb_transport.api.responses` | Core app | Transport services | 7 days | 10 |
| `tb_transport.notifications` | Core app | Transport services | 7 days | 1 |
| `tb_rule_engine` | Core app | Rule engine | 7 days | 1 |
| `tb_core` | Rule engine, transports | Core app | 7 days | 10 |
| `tb_housekeeper` | Core app | Housekeeper service | 7 days | 10 |
| `tb_ota_package` | Core app | Core app | 7 days | 10 |
| `tb_usage_stats` | Core/transport | Core app | 7 days | 1 |
| `js.eval.requests` | Rule engine | JS executor | 1 day | 30 |
| `js.eval.responses` | JS executor | Rule engine | 1 day | 30 |
| `tb.calculated-field` | Core app | CF service | 7 days | 1 |
| `edqs.events` | Core app | EDQS | 1 day | 12 |
| `edqs.state` | EDQS | EDQS | ∞ (compacted) | 12 |

**Kafka Producer settings:**
- `acks=all` — no data loss
- Batch size: 16 KB, linger: 1 ms
- Max request size: 1 MB, buffer: 32 MB

---

### 5.3 Core Application Server

**Entry point:** `ThingsboardServerApplication` (annotated with `@SpringBootApplication`, `@EnableAsync`, `@EnableScheduling`)

**Package:** `org.thingsboard.server`

The core application is responsible for:

1. **REST API** — 50+ controllers under `/api/**` exposing CRUD for devices, assets, dashboards, rule chains, users, tenants, alarms, widgets, and more. Served on port 8080.
2. **WebSocket API** — Real-time subscriptions for telemetry, attributes, and alarms. A browser widget subscribes to `ws://host:8080/api/ws/plugins/telemetry?token=<JWT>` and receives live updates without polling.
3. **Processing transport messages** — Consumes `tb_transport.api.requests`, validates device session, writes telemetry/attributes, and routes to rule engine.
4. **Device state management** — Tracks connected/disconnected/active/inactive device states in memory and persists changes.
5. **Alarm lifecycle** — Creates, updates, clears, and acknowledges alarms based on device profile rules.
6. **OTA management** — Coordinates firmware/software updates by tracking device firmware versions and streaming chunks.
7. **Housekeeper** — TTL-based cleanup of stale time-series data, events, and alarms.
8. **API usage tracking** — Meters API calls per tenant, enforces rate limits, and reports to billing.

**Key service classes** (under `application/src/main/java/org/thingsboard/server/service/`):

| Service | Responsibility |
|---|---|
| `DefaultTbDeviceService` | Device CRUD + profile validation |
| `DefaultTbTelemetryService` | Telemetry write path |
| `DefaultSessionMetaData` | Transport session registry |
| `DefaultDeviceStateService` | Device connectivity tracking |
| `DefaultTbAlarmService` | Alarm creation and lifecycle |
| `TbApiUsageStateService` | Rate limiting and usage metering |
| `DefaultOtaPackageStateService` | Firmware OTA coordination |
| `DefaultTbRuleEngineService` | Rule chain lookup and routing |
| `DefaultSubscriptionManagerService` | WebSocket subscription fan-out |
| `DefaultTbQueueService` | Rule engine queue management |
| `AiChatModelService` | AI/LLM integration |
| `NotificationSchedulerService` | Scheduled notification delivery |

---

### 5.4 Actor System

ThingsBoard implements a **custom actor model** (similar to Akka but simpler) to manage concurrent, stateful entities without shared mutable state.

**Core classes** (`common/actor/`):

| Class | Role |
|---|---|
| `DefaultTbActorSystem` | Manages actor lifecycle, dispatcher threads, mailboxes |
| `TbActorMailbox` | Per-actor bounded message queue |
| `Dispatcher` | Thread pool that drains actor mailboxes |
| `AbstractTbActor` | Base class; implement `process(TbActorMsg)` |
| `TbActorId` / `TbEntityActorId` | Unique actor identifiers (entity type + UUID) |

**Actor Hierarchy:**

```
AppActor (1 per JVM)
└── TenantActor (1 per tenant)
    ├── DeviceActor (1 per connected device)
    │   └── handles: telemetry, RPC, attribute updates, device profile
    ├── RuleChainActor (1 per rule chain)
    │   └── RuleNodeActor (1 per node in the chain)
    ├── StatsActor (statistics collection)
    └── CalculatedFieldManagerActor
        └── CalculatedFieldEntityActor (1 per device with CF)
```

**Dispatcher thread pools (configurable):**

| Dispatcher | Default Threads | What it runs |
|---|---|---|
| `app_dispatcher` | 1 | Top-level AppActor |
| `tenant_dispatcher` | 2 | TenantActor messages |
| `device_dispatcher` | 4 | DeviceActor messages |
| `rule_dispatcher` | 8 | Rule engine actors |
| `edge_dispatcher` | 4 | Edge device actors |
| `cfm_dispatcher` | 2 | Calculated field manager |
| `cfe_dispatcher` | 8 | Calculated field entity actors |

**Message types** (all implement `TbActorMsg`):

- `TbMsg` — the universal IoT message (telemetry, attribute, RPC, alarm, lifecycle)
- `ToDeviceActorNotificationMsg` — downlink notification to a device actor
- `TbRuleEngineActorMsg` — wraps a `TbMsg` for rule engine routing
- `ToCalculatedFieldSystemMsg` — triggers calculated field recomputation
- `CalculatedFieldStatePartitionRestoreMsg` — restores actor state after restart

---

### 5.5 Rule Engine

The rule engine processes every `TbMsg` through a **directed graph of rule nodes** called a **Rule Chain**.

**Rule Chain concepts:**
- Each tenant has one root rule chain (and may have sub-chains).
- A rule chain is a DAG. Nodes are connected with labeled relations: `Success`, `Failure`, `True`, `False`, `Other`, custom labels.
- Each rule chain runs inside a `RuleChainActor` → `RuleNodeActor` hierarchy.

**Core API** (`rule-engine-api/`):

| Interface | Purpose |
|---|---|
| `TbContext` | Execution context injected into every node; provides access to all platform services (DAO, queues, alarms, notifications, AI, etc.) |
| `TbNode` | Interface every rule node implements: `init(config)`, `onMsg(ctx, msg)`, `destroy()` |
| `RuleEngine` | Submits messages to the rule engine queue |

**Built-in Rule Node Categories:**

| Category | Nodes (examples) |
|---|---|
| **Filter** | Message type filter, script filter, device profile filter, originator type filter |
| **Enrichment** | Add originator attributes, customer/tenant details, related entity data |
| **Transformation** | Script transform, rename keys, JSON path, change originator |
| **Action** | Save telemetry, save attributes, create alarm, clear alarm, assign to customer |
| **External** | REST API call, MQTT publish, Kafka publish, RabbitMQ, GCP Pub/Sub, AWS SNS/SQS/Lambda, Azure MQTT |
| **Notification** | Send email, send SMS, send to Slack, platform notifications |
| **RPC** | RPC call reply, RPC call request |
| **Flow** | Rule chain, checkpoint (queue persistence), switch, delay |
| **Math** | Math function, calculate delta |
| **Geo** | Geofencing (entry/exit) |
| **AI** | AI model invocation |
| **Deduplication** | Message deduplication |
| **Edge** | Push to edge, assign to edge |
| **Debug** | Log message |

**JavaScript execution** — Script-based nodes (filter, transform) compile and run JS in an isolated sandbox. In microservices mode, this is offloaded to the `tb-js-executor` service via the `js.eval.*` Kafka topics, preventing slow scripts from blocking the JVM.

**Error handling** — A node's `onFailure` path can route to another node. Unhandled failures are persisted as `ERROR` events on the originating entity.

---

### 5.6 Data Access Layer (DAO)

The DAO layer provides a **unified interface** for all persistence operations, with pluggable backends.

**Storage topology:**

```
┌─────────────────────────────────────────────────────────────┐
│                  PostgreSQL (always required)                │
│  Entities: Device, Asset, Tenant, Customer, User            │
│  Alarms, Dashboards, Widgets, Rule Chains                   │
│  Attributes (server-side, shared, client-side)              │
│  SQL Time-Series (default) — partitioned by month           │
│  Audit log, Events                                          │
└─────────────────────────────────────────────────────────────┘
         │ optional hybrid mode
┌────────▼────────────────────────────────────────────────────┐
│              Cassandra (time-series only)                    │
│  High-throughput telemetry writes (millions of points/sec)  │
│  Keyspace: thingsboard, Consistency: ONE                    │
│  Partitioned by: MONTHS (configurable)                      │
│  TTL configurable per data point                            │
└─────────────────────────────────────────────────────────────┘
         │ optional
┌────────▼────────────────────────────────────────────────────┐
│              TimescaleDB (time-series only)                  │
│  Hyper-table based, auto-chunking + compression             │
│  Native PostgreSQL compatibility                            │
└─────────────────────────────────────────────────────────────┘
```

**Configuration flag:**
```yaml
database:
  ts:
    type: "${DATABASE_TS_TYPE:sql}"        # sql | cassandra | timescale
  ts_latest:
    type: "${DATABASE_TS_LATEST_TYPE:sql}" # sql | cassandra
```

**Batch write optimization:**

| Table | Batch size | Max delay |
|---|---|---|
| Attributes | 1,000 rows | 50 ms |
| Time-series (historical) | 10,000 rows | 100 ms |
| Time-series (latest values) | 1,000 rows | 50 ms |

**Cassandra specifics:**
- Cluster: `Thingsboard Cluster`, keyspace: `thingsboard`
- Query buffers: 200K max queue, 1,000 concurrent sessions
- Connect timeout: 5 s, read timeout: 20 s
- Optional DataStax Astra Cloud support

---

### 5.7 EDQS — Entity Data Query Service

EDQS provides **advanced entity search and filtering** beyond what standard JPA queries can efficiently handle. It maintains a local RocksDB state store of entity metadata, synchronized via Kafka compacted topics.

**Modes:**
- `local` (monolith) — embedded in the same JVM
- `remote` — separate `tb-edqs` microservice

**How it works:**
1. Core app publishes entity change events to `edqs.events` Kafka topic.
2. EDQS consumer updates its RocksDB state store.
3. Entity queries from the UI (complex multi-filter, relation traversal) are dispatched to EDQS via `edqs.requests` / `edqs.responses` topics.
4. Results are returned to the core app and then to the REST client.

**Performance:** Slow query threshold logged at 3 seconds. Max pending requests: 10,000. Request timeout: 20 s.

---

### 5.8 Web UI (Angular Frontend)

**Framework:** Angular 20.3.19 with Angular Material 20.2.14 and NgRx for state management.

**Key frontend capabilities:**
- **Dashboards** — drag-and-drop widget canvas with live WebSocket subscriptions
- **Entity management** — CRUD for devices, assets, customers, tenants, rule chains, users
- **Rule chain editor** — visual graph editor (nodes + relations)
- **Alarm management** — alarm table with filtering and acknowledgement
- **Widget library** — charts (ECharts), maps (Leaflet), tables, gauges, image overlays
- **OTA management** — firmware upload and device targeting
- **Version control** — Git-backed configuration snapshots
- **i18n** — ngx-translate for multi-language support

**Communication pattern:**
- **REST API** for CRUD: `GET/POST/PUT/DELETE /api/**`
- **WebSocket** for live data: `ws://.../api/ws/plugins/telemetry` — subscribes to entity time-series/attribute streams; pushes updates to widgets without polling.

**Build:** Production build requires up to 4 GB Node.js heap (`--max-old-space-size=4096`).

---

### 5.9 Caching Layer

| Mode | Backend | Use case |
|---|---|---|
| `caffeine` | In-process Caffeine | Single-node deployments |
| `redis` | Valkey/Redis (Standalone, Cluster, Sentinel) | Distributed, multi-node |

**What is cached:**
- Device credentials (prevent DB round-trips on every message)
- Tenant profile settings
- Device profiles
- Security tokens (JWT blacklist)
- Widget bundles

---

### 5.10 Cluster Coordination

**ZooKeeper** provides service registry and leader election in multi-node deployments.

- Each `tb-node` instance registers itself in ZooKeeper on startup at `/thingsboard/<serviceType>/<serviceId>`.
- Partition assignments are negotiated via ZooKeeper (each Kafka partition is owned by one node).
- When a node fails, ZooKeeper notifies survivors which re-balance partition ownership and restart actors for the migrated partitions.
- **Inter-node RPC** uses gRPC + Protocol Buffers for low-latency calls (e.g., pushing a notification from the node that owns the rule engine actor to the node that owns the device's transport session).

---

### 5.11 Monitoring

**Spring Boot Actuator** exposes metrics at `/actuator/metrics`.

**Prometheus + Grafana** (via `docker-compose.prometheus-grafana.yml`):
- Queue consumer lag (Kafka)
- Actor mailbox size and processing latency
- Rule engine throughput
- DB query latency (Cassandra stats printed every 10 s)
- SQL batch stats printed every 10 s

---

## 6. Data Flow Walkthrough

The following describes the **complete telemetry ingestion flow** from device to dashboard, step by step.

```
Device                 Transport            Queue            Core / Rule Engine        DB          Browser
  │                       │                  │                      │                   │              │
  │──MQTT PUBLISH─────────▶│                  │                      │                   │              │
  │  topic: v1/.../telemetry                  │                      │                   │              │
  │  payload: {"temp":23.4}                   │                      │                   │              │
  │                        │                  │                      │                   │              │
  │                        │─validate token───▶CredentialCache       │                   │              │
  │                        │◀──device found───  (Caffeine/Redis)     │                   │              │
  │                        │                  │                      │                   │              │
  │                        │─build TbMsg──────▶tb_transport.api      │                   │              │
  │                        │                  │   .requests (Kafka)  │                   │              │
  │                        │                  │                      │                   │              │
  │                        │                  │──consume msg─────────▶CoreService        │              │
  │                        │                  │                      │  .processMsg()    │              │
  │                        │                  │                      │                   │              │
  │                        │                  │                      │─route to rule─────▶              │
  │                        │                  │                      │  engine queue     │              │
  │                        │                  │                  tb_rule_engine (Kafka)  │              │
  │                        │                  │                      │                   │              │
  │                        │                  │                      │─TenantActor       │              │
  │                        │                  │                      │  └─RuleChainActor │              │
  │                        │                  │                      │     └─Node: Filter (msg type)   │
  │                        │                  │                      │        └─Node: Save Telemetry   │
  │                        │                  │                      │                   │              │
  │                        │                  │                      │─batch write───────▶PostgreSQL    │
  │                        │                  │                      │  (10K rows/100ms) │  ts_kv table │
  │                        │                  │                      │                   │              │
  │                        │                  │                      │─publish WS event──────────────── ▶
  │                        │                  │                      │  (SubscriptionMgr)│           Browser
  │                        │                  │                      │                   │         updates
  │                        │                  │                      │                   │          widget
```

**If an alarm condition is met** (e.g. temp > 30°C), the rule chain routes the `TbMsg` to a **Create Alarm** node, which:
1. Calls `AlarmService.createOrUpdateAlarm()` → persists in PostgreSQL.
2. Emits a `TbMsg` of type `ALARM` back into the rule chain (alarm rule chain can then trigger email/SMS via notification nodes).
3. Pushes a WebSocket event to all subscribed browser sessions.

**RPC downlink flow:**

```
Browser ─POST /api/plugins/rpc/{deviceId}─▶ REST Controller
         ▶ CoreService.sendRpcRequest()
         ▶ publishes to tb_core queue
         ▶ DeviceActor receives RpcRequestToDeviceActorMsg
         ▶ TransportService pushes to device via tb_transport.notifications
         ▶ Device receives over MQTT: v1/devices/me/rpc/request/{id}
         ▶ Device replies: v1/devices/me/rpc/response/{id}
         ▶ Transport publishes response to tb_transport.api.requests
         ▶ CoreService resolves the pending RPC future
         ▶ REST API returns HTTP 200 with response payload to browser
```

---

## 7. Real-World Example — Smart Cold-Chain Monitoring

**Scenario:** A pharmaceutical company tracks 500 refrigerated trucks. Each truck has a temperature/humidity sensor that reports every 30 seconds. If temperature exceeds 8°C for more than 2 minutes, an alarm is raised and the operations team is notified by email and SMS. A live dashboard displays all trucks on a map.

### Step 0 — Provisioning

An administrator logs into the Angular UI, creates a **Tenant** (`PharmaLogistics`), a **Device Profile** (`RefrigeratedTruck`) with:
- Transport: MQTT
- Alarm rule: `temperature > 8` for > 2 min → create alarm `HIGH_TEMP`, severity `CRITICAL`
- Default rule chain: `Cold Chain Monitoring`

500 device records are bulk-imported via CSV. Each device gets a unique **access token** (e.g., `truck-001-token`).

### Step 1 — Device Connection

Truck sensor firmware connects to ThingsBoard's MQTT broker:

```
CONNECT  host=thingsboard.pharma.com  port=1883
         clientId=truck-001
         username=truck-001-token
         password=(empty)
```

**Inside ThingsBoard:**
- `MqttTransportService` (Netty handler) receives the `CONNECT` packet.
- Looks up the token `truck-001-token` → hits `DeviceCredentialsCache` (Caffeine/Redis).
- On miss, queries PostgreSQL `device_credentials` table; caches the result.
- Creates a `DeviceSessionCtx` in memory and registers it.
- Sends `CONNACK` (returnCode=0) to the device.

### Step 2 — Telemetry Publish

Every 30 seconds the truck publishes:

```
PUBLISH  topic=v1/devices/me/telemetry
         QoS=1
         payload={"temperature":6.8,"humidity":72,"location":{"lat":40.71,"lon":-74.01}}
```

**Inside ThingsBoard:**
- `MqttTransportService` receives the `PUBLISH`.
- Parses JSON payload into key-value pairs.
- Builds a `TbMsg`:
  ```
  TbMsg {
    id: <UUID>
    type: POST_TELEMETRY_REQUEST
    originator: EntityId(DEVICE, truck-001-uuid)
    metaData: { deviceName="truck-001", deviceType="RefrigeratedTruck" }
    data: '{"temperature":6.8,"humidity":72,"location":{...}}'
    ts: 1746280800000
  }
  ```
- Serializes to Protobuf and publishes to Kafka topic `tb_transport.api.requests` (partition chosen by device UUID hash → deterministic routing).

### Step 3 — Core Processing

The `tb-node` instance owning that partition consumes the message:
1. `DefaultSessionMetaData` confirms session is active.
2. `DefaultTbTelemetryService.processTelemetry()` is called.
3. Publishes the `TbMsg` to the `tb_rule_engine` Kafka topic.

### Step 4 — Rule Engine Processing

The `RuleChainActor` for tenant `PharmaLogistics` routes the `TbMsg` through the **Cold Chain Monitoring** rule chain:

```
[Message Type Filter] ─True─▶ [Originator Type Filter (DEVICE)]
    │
    └─True─▶ [Enrich: Add device attributes (truck ID, driver, route)]
                  │
                  └─▶ [Device Profile Check / Alarm Rule Eval]
                             │
                  temp ≤ 8°C └─No Alarm─▶ [Save Telemetry Node]
                  temp > 8°C └─Alarm─────▶ [Create Alarm: HIGH_TEMP CRITICAL]
                                                    │
                                        ┌───────────┴──────────────┐
                                        │                          │
                                [Send Email Node]         [Send SMS Node]
                                (ops@pharma.com)         (+1-555-OPS-TEAM)
```

**Save Telemetry Node:**
- Calls `TbContext.getTelemetryService().saveAndNotify(...)`.
- The DAO batches the write: when 10,000 rows accumulate (or 100 ms pass), it executes a single `INSERT INTO ts_kv ...` bulk statement into PostgreSQL.
- Simultaneously triggers a WebSocket notification event.

**Alarm node** (when temperature = 9.3°C):
- `AlarmService.createOrUpdateAlarm()`:
  - Checks if an `ACTIVE` alarm of type `HIGH_TEMP` already exists for `truck-001`.
  - If new: inserts into `alarm` table in PostgreSQL.
  - If existing but worsening: updates severity.
- Emits a new `TbMsg` of type `ALARM` back into the rule chain.
- `Send Email Node` calls `MailService.sendEmail()` to `ops@pharma.com`:
  ```
  Subject: [CRITICAL] HIGH_TEMP alarm on truck-001
  Body: Temperature 9.3°C detected at 2026-05-03 14:00:00 UTC.
        Location: 40.71°N, -74.01°W
  ```
- `Send SMS Node` calls configured SMS provider (e.g., Twilio): `"ALERT: truck-001 temp 9.3°C. Act now."`

### Step 5 — Real-Time Dashboard

The operations supervisor has a ThingsBoard dashboard open in Chrome:

- A **map widget** (Leaflet) subscribes via WebSocket to the `location` attribute of all 500 devices.
  - Subscription: `ws://thingsboard.pharma.com/api/ws/plugins/telemetry`
  - Each truck appears as a pin; alarming trucks show in red.
- A **time-series chart widget** (ECharts) shows the last 24 hours of `temperature` for the selected truck.
- An **alarm table widget** lists all active alarms with severity, time, and status.

When the supervisor acknowledges the alarm in the dashboard, the browser calls:
```
POST /api/alarm/{alarmId}/acknowledge
```
The `AlarmController` calls `AlarmService.acknowledgeAlarm()`, which updates the alarm record in PostgreSQL and pushes the state change to all subscribed WebSocket sessions.

### Step 6 — RPC Downlink (optional)

The supervisor remotely triggers the truck's refrigeration unit restart from the dashboard:

```
POST /api/plugins/rpc/twoway/{deviceId}
Body: {"method":"restartUnit","params":{"delay":5}}
```

The message travels: REST API → CoreService → Kafka `tb_core` → DeviceActor → `tb_transport.notifications` → MQTT broker → device over topic `v1/devices/me/rpc/request/42`. The device executes the command and responds on `v1/devices/me/rpc/response/42`. The response propagates back synchronously to the browser as the HTTP response body.

---

## 8. Deployment Modes

### Monolith (All-in-One)

All services (transport, rule engine, core, EDQS) run in a single JVM. Queue is in-memory. Database is either embedded HSQLDB (demo) or external PostgreSQL.

```bash
# Docker single-instance
docker run -p 8080:8080 -p 1883:1883 thingsboard/tb-postgres
```

### Hybrid Microservices (Production)

Each concern is a separate Docker service, coordinated by Kafka and ZooKeeper.

```yaml
# docker-compose.yml (simplified excerpt)
services:
  tb-node:          image: thingsboard/tb-node        # Core + Rule Engine
  tb-mqtt-transport: image: thingsboard/tb-mqtt-transport
  tb-http-transport: image: thingsboard/tb-http-transport
  tb-coap-transport: image: thingsboard/tb-coap-transport
  tb-lwm2m-transport: image: thingsboard/tb-lwm2m-transport
  tb-snmp-transport: image: thingsboard/tb-snmp-transport
  tb-js-executor:   image: thingsboard/tb-js-executor  # 10 replicas
  tb-vc-executor:   image: thingsboard/tb-vc-executor
  tb-web-ui:        image: thingsboard/tb-web-ui        # Express.js
  tb-edqs:          image: thingsboard/tb-edqs
  kafka:            image: confluentinc/cp-kafka
  zookeeper:        image: confluentinc/cp-zookeeper
  postgres:         image: postgres:16
  valkey:           image: valkey/valkey:7.2
```

**Scaling:** `tb-node`, `tb-mqtt-transport`, and `tb-js-executor` can all be scaled horizontally. Kafka partitioning ensures each device's messages are processed in order on a single node.

---

## 9. Security Architecture

| Concern | Implementation |
|---|---|
| **User authentication** | JWT (2.5 h access token, 1 week refresh). Signed with HMAC-SHA512. Issuer: `thingsboard.io`. |
| **OAuth2 / SSO** | Configurable OAuth2 providers (GitHub, Google, custom OIDC) |
| **Device authentication** | Access token, X.509 certificate, Basic Auth |
| **Transport encryption** | TLS on all transports (MQTT:8883, HTTPS, CoAP+DTLS) |
| **API security** | JWT bearer token on all REST endpoints; role-based (SYS_ADMIN, TENANT_ADMIN, CUSTOMER_USER) |
| **Multi-tenancy isolation** | Every DB query is scoped by `tenant_id`; actors are per-tenant |
| **SSRF protection** | Configurable block list of private IP ranges for outbound HTTP from rule nodes |
| **Device claiming** | Duration-limited (1 day default) secret-based claiming |
| **API key** | Auto-generated 64-byte keys with `tb_` prefix for programmatic access |
| **Security headers** | X-Content-Type-Options, Referrer-Policy configured; X-Frame-Options relaxed for dashboard embedding |

---

## 10. Key Configuration Reference

All settings are in [application/src/main/resources/thingsboard.yml](application/src/main/resources/thingsboard.yml) and can be overridden with environment variables.

| Setting | Env Var | Default | Purpose |
|---|---|---|---|
| HTTP bind port | `HTTP_BIND_PORT` | `8080` | REST API & UI |
| MQTT bind port | `MQTT_BIND_PORT` | `1883` | MQTT transport |
| CoAP bind port | `COAP_BIND_PORT` | `5683` | CoAP transport |
| Queue type | `TB_QUEUE_TYPE` | `in-memory` | `kafka` or `in-memory` |
| DB time-series | `DATABASE_TS_TYPE` | `sql` | `sql`, `cassandra`, `timescale` |
| Cache type | `CACHE_TYPE` | `caffeine` | `caffeine` or `redis` |
| ZooKeeper enable | `ZOOKEEPER_ENABLED` | `false` | Enable for cluster mode |
| JWT token TTL | `JWT_TOKEN_EXPIRATION_TIME` | `9000` (s) | 2.5 hours |
| JWT refresh TTL | `JWT_REFRESH_TOKEN_EXPIRATION_TIME` | `604800` (s) | 1 week |
| JS executor mode | `JS_EVALUATOR` | `local` | `local` or `remote` |
| EDQS enabled | `EDQS_ENABLED` | `false` | Enable entity query service |
| Actor rule threads | `ACTORS_RULE_POOL_SIZE` | `8` | Rule engine thread pool |
| Actor device threads | `ACTORS_DEVICE_POOL_SIZE` | `4` | Device actor thread pool |
| Kafka brokers | `TB_KAFKA_SERVERS` | `localhost:9092` | Kafka bootstrap servers |

---

*This document was generated from the ThingsBoard 4.4.0-SNAPSHOT source tree on 2026-05-03.*
