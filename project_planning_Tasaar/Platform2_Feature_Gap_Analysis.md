# Platform 2 — Feature Coverage & Backend Additions
## What ThingsBoard CE gives us, what we use, what we add

> Date: 2026-05-03

---

## The Honest One-Paragraph Answer

Platform 2 gets **all of ThingsBoard CE's device connectivity and telemetry engine for free**, but ThingsBoard CE alone does **not** natively handle BACnet, Modbus, OPC-UA, or KNX — those require the separate **ThingsBoard IoT Gateway** (also open-source, Apache 2.0). With the Gateway included, the protocol coverage matches a mid-tier SCADA system for data ingestion. However, ThingsBoard CE + Gateway is still **not a SCADA** in the full industrial sense — it has no ladder logic, no PLC programming environment, no process control loops, and no HMI in the traditional sense. Platform 2 compensates by adding AI-driven operations intelligence on top, which is a different and more valuable layer than trying to clone a SCADA.

---

## Part 1 — What ThingsBoard CE Gives Us (Full Feature Inventory)

### 1.1 Device Protocols — Built into ThingsBoard CE Server

| Protocol | Support Level | Notes |
|---|---|---|
| **MQTT 3.1 / 3.1.1** | Native, full | Custom Netty broker. QoS 0/1/2. TLS on port 8883. |
| **HTTP / HTTPS** | Native, full | REST endpoint for telemetry push. Supports JSON and binary. |
| **CoAP** | Native, full | Eclipse Californium. UDP. Useful for constrained sensors. |
| **LwM2M** | Native, full | Eclipse Leshan. OTA firmware over LwM2M. For LPWAN/cellular IoT. |
| **SNMP v1/v2c/v3** | Native, full | SNMP trap collector + polling. Primary NMS protocol. |
| **WebSocket** | Native (upstream push) | Browser and API clients subscribe to live telemetry. |

### 1.2 Device Protocols — Require ThingsBoard IoT Gateway (Separate but Free)

> **ThingsBoard IoT Gateway** is a standalone Python-based open-source component (Apache 2.0). It runs as a Docker container alongside TB CE and bridges industrial protocols to MQTT/TB. It must be included in the Platform 2 Docker Compose stack.

| Protocol | Via IoT Gateway | Notes |
|---|---|---|
| **Modbus TCP** | Yes | Poll registers from PLCs, VFDs, meters. R/W capable. |
| **Modbus RTU** | Yes | Serial RS-485 devices. Via USB-serial or serial server. |
| **BACnet/IP** | Yes | Building automation controllers (HVAC, chillers, AHUs). |
| **BACnet MS/TP** | Yes | RS-485 serial BACnet (older BMS installations). |
| **OPC-UA** | Yes | Industrial PLCs and SCADA historians (Siemens, Allen-Bradley, Wonderware). Read + subscribe to nodes. **Write** to OPC-UA nodes also supported — enables setpoint commands. |
| **KNX** | Yes | Building automation bus (lighting, HVAC, shading). |
| **EtherNet/IP** | Yes | Allen-Bradley PLCs, Rockwell Automation. |
| **CAN bus** | Yes | Automotive / industrial via serial adapter. |
| **FTP** | Yes | File-based data collection from legacy systems. |
| **REST** | Yes | Poll third-party APIs (weather, tariff, external SCADA). |
| **gRPC** | Via TB server directly | Supported in ThingsBoard CE server natively. |

**Bottom line on protocols:** With the IoT Gateway included in the stack, Platform 2 covers every protocol mentioned in the architecture document — MQTT, SNMP, BACnet, Modbus, gRPC, REST, KNX, and OPC-UA. No additional licensed software is required.

---

### 1.3 Core ThingsBoard CE Feature Set (What We Inherit)

#### Device & Asset Management
| Feature | ThingsBoard CE | Platform 2 Exposure |
|---|---|---|
| Device registry with metadata | Yes — full CRUD | Internal via FastAPI ThingsBoard Adapter |
| Device profiles (protocol, credentials, alarm rules) | Yes | Internal |
| Asset hierarchy (building → floor → zone → device) | Yes | Exposed to React frontend via FastAPI |
| Entity relations (belongs-to, contains, manages) | Yes | Used internally for topology graph |
| Customer management (multi-tenant) | Yes | Replaced by Platform 2's own RBAC |
| Bulk device import (CSV) | Yes | Exposed via FastAPI Device Onboarding Service |
| QR code provisioning | Yes | Internal |

#### Telemetry & Attributes
| Feature | ThingsBoard CE | Platform 2 Exposure |
|---|---|---|
| Time-series telemetry storage (PostgreSQL / Cassandra / TimescaleDB) | Yes | Internal storage — queried via TB REST by FastAPI |
| Attribute types: server-side, shared, client-side | Yes — all three | Internal — shared attributes used for device config |
| Real-time WebSocket telemetry push | Yes (TB-side) | Replaced by Platform 2's own WebSocket from FastAPI |
| Telemetry retention and TTL | Yes | Internal |
| Calculated fields (derived metrics) | Yes (new in v4.x) | Could be used internally for pre-computed KPIs |

#### Rule Engine
| Feature | ThingsBoard CE | Platform 2 Use |
|---|---|---|
| Visual rule chain editor | Yes (TB UI — internal only) | Used internally to configure alarm triggers and Kafka webhooks. Operators never see the TB rule chain editor. |
| 30+ built-in rule nodes (filter, transform, enrich, action) | Yes | Used internally for: alarm threshold detection → FastAPI webhook call |
| JavaScript script nodes | Yes | Internal |
| REST API call node | Yes | TB calls FastAPI Alert Service on alarm events |
| Kafka publish node | Yes | Core integration point — TB streams telemetry to Kafka |
| MQTT publish / Email / SMS nodes | Yes | Bypassed — Platform 2 handles all notifications via FastAPI |
| Geofencing rule node | Yes | Can be used internally |

#### Alarm System (TB Native)
| Feature | ThingsBoard CE | Platform 2 Use |
|---|---|---|
| Alarm rule configuration per device profile | Yes | Used internally — threshold alarms trigger Kafka + FastAPI webhook |
| Alarm lifecycle (create, acknowledge, clear, comment) | Yes | FastAPI Alert Service calls TB REST to acknowledge alarms |
| Alarm severity levels | Yes | TB alarm severity mapped to Platform 2 severity palette |
| Alarm propagation to assets | Yes | Internal |
| Alarm notifications | Yes (TB UI) | Bypassed — Platform 2 does enriched AI notifications |

#### Bidirectional Device Control (RPC)
| Feature | ThingsBoard CE | Platform 2 Exposure |
|---|---|---|
| One-way RPC (server → device, fire-and-forget) | Yes — `RpcV1Controller` | Exposed via FastAPI as device command endpoint |
| Two-way RPC (server → device → response, with timeout) | Yes — `RpcV2Controller` | Exposed via FastAPI — used for HVAC setpoint change, relay toggle |
| RPC from device → server (device-initiated) | Yes | Internal |
| RPC persistence (queued for offline devices) | Yes | Internal |
| RPC rule node (trigger RPC from rule chain) | Yes | Internal — AI could auto-trigger RPC on predictive action |

> **This is the closest ThingsBoard gets to SCADA control.** RPC allows Platform 2 to send a setpoint change command to a PLC (via OPC-UA gateway), toggle a relay on an HVAC unit, or restart a network device — and get a confirmation response. It is not a real-time control loop, but it covers most remote command use cases.

#### OTA Firmware / Software Updates
| Feature | ThingsBoard CE | Platform 2 Exposure |
|---|---|---|
| Firmware package upload and versioning | Yes | Exposed via FastAPI OTA Service |
| Per-device firmware targeting | Yes | Exposed |
| OTA delivery over MQTT / LwM2M | Yes | Internal delivery mechanism |
| Update status tracking (downloading, verified, failed) | Yes | Exposed to React frontend |

#### Edge Computing (ThingsBoard Edge)
| Feature | ThingsBoard CE | Platform 2 Use |
|---|---|---|
| Push rule chains / dashboards to edge nodes | Yes (TB Edge is free) | **Partially used** — edge nodes run ML inference containers (Isolation Forest per site) alongside TB Edge for offline buffer |
| Edge-to-cloud sync when connectivity restored | Yes | Used for offline buffer |
| Local alarm processing at edge | Yes | Used for sub-100ms response without cloud round-trip |

#### Security & Multi-Tenancy
| Feature | ThingsBoard CE | Platform 2 Use |
|---|---|---|
| Multi-tenant namespace isolation | Yes | Used — each Platform 2 customer = one TB tenant |
| JWT authentication (TB API) | Yes | Internal — FastAPI ThingsBoard Adapter holds the TB service account JWT |
| Device credentials: access token, X.509, Basic Auth | Yes | All three supported |
| 2FA | Yes | Bypassed — Platform 2 Auth Service handles 2FA |
| OAuth2 / SSO | Yes (TB-side) | Bypassed — Platform 2 Auth Service handles OAuth2 |
| RBAC | Yes (TB-side) | Bypassed — Platform 2 has its own finer-grained RBAC |
| Audit log | Yes | Available via TB REST if needed |

#### Version Control & Configuration
| Feature | ThingsBoard CE | Platform 2 Use |
|---|---|---|
| Git-backed config snapshots (rule chains, dashboards, device profiles) | Yes | Internal — useful for multi-tenant config management |
| Auto-commit to Git | Yes | Internal |

#### Analytics
| Feature | ThingsBoard CE | Platform 2 Use |
|---|---|---|
| Trendz Analytics (built-in BI — `TrendzController`) | Yes (basic) | Bypassed — Platform 2 builds its own AI-powered analytics |
| Native dashboards + 30+ widget types | Yes | Bypassed — React frontend replaces entirely |
| API usage tracking and rate limiting | Yes | Internal |

---

### 1.4 What ThingsBoard CE Does NOT Have (Honest Gaps)

| Missing Feature | Impact on Platform 2 | Mitigation |
|---|---|---|
| **No ladder logic / PLC programming** | Cannot program PLCs from the platform | Not in scope — Platform 2 is an operations intelligence platform, not a PLC IDE |
| **No real-time closed-loop control** | Cannot run a PID controller loop | OPC-UA write via IoT Gateway + RPC covers setpoint changes; sub-100ms loop control requires edge runtime (separate) |
| **No SCADA HMI process diagrams** | No classic SCADA valve/pump/pipe animated schematic | Platform 2's Floor Map (Deck.gl + SVG) serves this role — clickable devices with live state overlays |
| **No native BACnet / Modbus / OPC-UA in CE server** | Requires IoT Gateway | IoT Gateway is open-source, free, and is part of the Platform 2 Docker stack |
| **No historian API (SCADA-grade)** | TB's time-series API is REST — not ODBC/OPC-HDA | TimescaleDB provides historian-quality querying for Platform 2's own analytics services |
| **No redundancy / hot-standby** | TB CE has no native active-passive failover | AKS pod replicas + PostgreSQL HA covers this in Platform 2's Azure deployment |
| **No certified safety (IEC 61511 / SIL)** | Cannot be used for safety-instrumented systems | Not in scope for BMS/NMS use case |

---

## Part 2 — What Platform 2 Adds on Top (New Backend Capabilities)

These are the features that **do not exist in ThingsBoard** at all and constitute Platform 2's actual IP.

### 2.1 AI / ML Intelligence Layer — Does Not Exist in ThingsBoard

#### A. Isolation Forest Anomaly Detection
- **What it does:** Scores every incoming telemetry event against a device-class-specific unsupervised model. Flags deviations beyond 3.4σ from a rolling 30-day baseline in real time on the Kafka stream.
- **ThingsBoard equivalent:** None. TB has threshold alarms (if `temp > X`). It has no statistical learning or adaptive baseline.
- **Why it matters:** Detects anomalies that have no static threshold — e.g., a chiller that normally draws 40A suddenly drawing 47A (not over a threshold, but statistically anomalous for this unit at this time of day).

#### B. LSTM Predictive Maintenance
- **What it does:** Runs a daily batch job on vibration, current draw, and temperature sequences per device. Outputs a `failure_probability` score and predicted failure window (24–72 hrs).
- **ThingsBoard equivalent:** None. TB has no time-series ML models.
- **Why it matters:** Converts reactive maintenance into scheduled maintenance. A work order is created before the failure occurs — reducing emergency callouts, parts expediting costs, and unplanned downtime.

#### C. GNN Root Cause Analysis
- **What it does:** When multiple alarms fire simultaneously (common in NMS cascade failures), a Graph Neural Network traverses the network topology adjacency matrix to identify the single root fault and its downstream blast radius. Returns result in under 8 seconds.
- **ThingsBoard equivalent:** None. TB can propagate alarms up an asset hierarchy (parent asset alarm when child device alarms), but it has no graph-based reasoning.
- **Why it matters:** Without root cause, operators see 40 simultaneous alarms and don't know where to start. GNN collapses 40 alarms to one root cause and a cascade path.

#### D. RAG Chat-to-Fix
- **What it does:** When an operator clicks an alert, a Chat panel opens with the device context pre-injected. The operator asks a plain-English question. LangChain retrieves the top-5 relevant documents from the vector store (device manuals, maintenance runbooks, fault-action pairs) and injects them as context into the LLM. The LLM streams a specific, actionable resolution.
- **ThingsBoard equivalent:** None. TB has no LLM integration, no RAG pipeline, no vector store.
- **Why it matters:** Reduces MTTR by giving Level-1 operators access to Level-3 knowledge without escalation. The resolution is specific to this device, this fault, at this site — not a generic manual excerpt.

#### E. Provider-Agnostic LLM Adapter
- **What it does:** `BaseLLMAdapter` interface with `stream_chat()`, `embed()`, `health_check()`. Implementations for Claude, GPT-4, Llama 3/Ollama, Azure OpenAI. Switch via one environment variable `LLM_PROVIDER=claude|openai|ollama|azure_openai`.
- **ThingsBoard equivalent:** ThingsBoard v4.x has an `AiModelController` (we can see it in the codebase), but it is for AI-assisted rule chain suggestions — not for RAG-based operational Q&A.
- **Why it matters:** On-premise customers (government, hospitals) can use Llama 3 with no cloud data egress. SaaS customers get Claude quality. No code change — just config.

---

### 2.2 Knowledge Base — Does Not Exist in ThingsBoard

| Component | What It Stores | How It Is Used |
|---|---|---|
| **Chroma / pgvector vector store** | Device manuals (PDF → chunks → embeddings), maintenance runbooks, vendor troubleshooting guides, SLA documents, network topology maps, CLI command references | LangChain top-5 retrieval at inference time — injected as LLM context |
| **Historical fault-action pairs** | Every resolved work order becomes a training record: `{device_class, fault_signature, resolution_steps, outcome}` | RAG retrieval — "how did we fix this exact fault on this device class last time?" |
| **Incremental RAG training loop** | Field technician logs resolution outcome in Mobile PWA | Continuously improves Chat-to-Fix response quality without retraining the LLM |

---

### 2.3 Work Order System — Does Not Exist in ThingsBoard

ThingsBoard has alarms. Alarms are not work orders. Platform 2 adds:

| Capability | Detail |
|---|---|
| **Auto-generated work orders** | On `CRITICAL` alarm or LSTM high-probability event, Work Order Service auto-populates: device ID, fault type, recommended steps (from LLM), required parts with procurement codes, required skill level, estimated labour hours, safety prerequisites |
| **Predictive work order queue** | Separate queue of LSTM-generated work orders sorted by `failure_probability` — facility manager approves before failure occurs |
| **CMMS integration** | ServiceNow, Remedy, SAP PM via REST webhook. Work order pushed with full schema mapping. |
| **ERP integration** | Parts procurement codes pushed to SAP / Oracle — parts ordered automatically |
| **Assignment and escalation** | Work order assigned to technician by skill, site, and availability. Escalation rules if not acknowledged within SLA |
| **Resolution tracking** | Field technician closes work order in Mobile PWA. Outcome logged. MTTR calculated per device class, per site. |

---

### 2.4 Alert Enrichment Service — Does Not Exist in ThingsBoard

ThingsBoard emits raw alarms: `{device_id, alarm_type, severity, timestamp}`. That's it.

Platform 2's **Alert Service** adds to every alarm:

```json
{
  "alert_id": "...",
  "device_id": "...",
  "device_name": "HVAC-AHU-03-F3",
  "site": "Tower B, Floor 3",
  "fault_type": "BEARING_VIBRATION_ANOMALY",
  "severity": "CRITICAL",
  "anomaly_score": 4.2,
  "sigma_deviation": "3.7σ from 30-day baseline",
  "root_cause": {
    "is_root": false,
    "actual_root_device": "NMS-SW-CORE-01",
    "cascade_path": ["NMS-SW-CORE-01", "NMS-SW-DIST-02", "HVAC-AHU-03-F3"]
  },
  "predicted_failure_window": "2026-05-05T08:00Z – 2026-05-06T08:00Z",
  "chat_context_url": "/api/chat?device_id=...&alert_id=...",
  "auto_work_order_id": "WO-2026-04471",
  "enriched_at": "2026-05-03T14:00:01Z"
}
```

This enriched alert is what the React frontend receives via WebSocket — not the bare TB alarm.

---

### 2.5 Multi-Tenant Auth & RBAC — Extends ThingsBoard's Model

ThingsBoard has tenants and customers. Platform 2 extends this with finer-grained RBAC:

| Role | Access |
|---|---|
| `SYSTEM_ADMIN` | All tenants, all sites, all data, system config |
| `FACILITY_MANAGER` | All sites within their tenant. Can approve/reject work orders. Cannot see other tenants. |
| `OPERATIONS_ENGINEER` | Assigned sites only. Can use Chat-to-Fix, acknowledge alerts. |
| `FIELD_TECHNICIAN` | Mobile PWA only. Can view and close assigned work orders. Cannot access dashboards. |
| `EXECUTIVE` | Read-only Executive Dashboard. KPIs only. No device-level detail. |

ThingsBoard's role model (TENANT_ADMIN, CUSTOMER_USER, SYS_ADMIN) is too coarse for this. Platform 2's Auth Service wraps the TB tenant model and implements its own JWT with role claims.

---

### 2.6 Executive KPI Aggregation — Does Not Exist in ThingsBoard

ThingsBoard has widgets that can display single-device metrics. It has no cross-device, cross-site KPI rollup. Platform 2 adds:

| KPI | How Computed |
|---|---|
| Energy anomaly cost estimate | `Σ(anomalous_consumption - baseline) × tariff_rate` per site, per month |
| MTTR (Mean Time to Resolve) | `avg(work_order.resolved_at - alert.created_at)` per device class |
| Uptime per device class | `1 - (downtime_minutes / total_minutes)` rolling 30-day |
| Predicted maintenance spend | LSTM failure probability × average repair cost per device class |
| Alarm frequency heatmap | `COUNT(alerts) GROUP BY site, device_class, hour_of_day` — identifies recurring fault patterns |
| Carbon / energy savings | `baseline_consumption - actual_consumption` after HVAC optimisation recommendation is implemented |

These are computed by FastAPI scheduled jobs (Celery beat) on TimescaleDB and cached in Redis for sub-100ms dashboard loads.

---

### 2.7 Edge Inference — Extends ThingsBoard Edge

ThingsBoard Edge can sync rule chains and telemetry offline. Platform 2 adds ML inference at the edge:

| Capability | Detail |
|---|---|
| **Per-site Isolation Forest container** | Anomaly model for each site's device class runs locally on the edge gateway. Scores events in under 100ms without cloud round-trip. |
| **Offline buffer** | When WAN connectivity is lost, ThingsBoard Edge buffers telemetry. Anomaly detection continues locally. Alerts fire locally. Chat-to-Fix unavailable (LLM requires cloud unless Ollama is running on-site). |
| **OTA model updates** | Retrained anomaly models are pushed to edge containers via Azure Blob + IoT Gateway OTA mechanism. |

---

### 2.8 Integration Gateway — Does Not Exist in ThingsBoard

Platform 2 exposes a standardised outbound event bus for downstream systems:

| Integration | What Is Pushed | Protocol |
|---|---|---|
| Platform 3 / external analytics | Enriched fault events with AI context | Kafka topic `platform.faults.outbound` |
| SCADA / historian (OSIsoft PI, Wonderware) | Normalised telemetry in PI AF schema | REST or Kafka → PI connector |
| ServiceNow / Remedy | Work orders | REST webhook |
| SAP PM / Oracle EAM | Parts procurement | REST |
| Power BI / Grafana | KPI time-series | TimescaleDB connector |
| Slack / Teams | Critical alert notifications | Webhook |

ThingsBoard has a REST API call rule node, but no structured outbound integration gateway with schema normalisation.

---

## Part 3 — Feature Comparison Table (ThingsBoard CE vs Platform 2)

| Feature Category | ThingsBoard CE Alone | Platform 2 (TB CE + FastAPI + AI) |
|---|:---:|:---:|
| **Protocol Connectivity** | | |
| MQTT / HTTP / CoAP / LwM2M / SNMP | Yes | Yes (via TB CE) |
| Modbus TCP/RTU | Via IoT Gateway | Yes (IoT Gateway included) |
| BACnet/IP + MS/TP | Via IoT Gateway | Yes (IoT Gateway included) |
| OPC-UA (read + write setpoint) | Via IoT Gateway | Yes (IoT Gateway included) |
| KNX | Via IoT Gateway | Yes (IoT Gateway included) |
| **Device Management** | | |
| Device registry + profiles | Yes | Yes (internal) |
| Asset hierarchy | Yes | Yes (exposed via FastAPI) |
| OTA firmware updates | Yes | Yes (exposed via FastAPI) |
| Bidirectional RPC (remote control) | Yes | Yes (exposed via FastAPI) |
| **Data Ingestion & Storage** | | |
| Time-series telemetry | Yes (TB internal) | Yes + TimescaleDB for analytics |
| Real-time WebSocket push | Yes (TB-side) | Yes (FastAPI-side, AI-enriched) |
| Telemetry TTL / retention | Yes | Yes |
| **Alarm / Alert Management** | | |
| Threshold-based alarms | Yes | Yes (TB internal) |
| Statistical anomaly detection | **No** | **Yes — Isolation Forest** |
| AI-enriched alert context | **No** | **Yes — Alert Service** |
| Root cause identification | **No** | **Yes — GNN (8s)** |
| **Predictive Capabilities** | | |
| Predictive maintenance | **No** | **Yes — LSTM (24-72 hr)** |
| Predictive work orders | **No** | **Yes** |
| **Natural Language Interface** | | |
| Chat-to-Fix (LLM) | **No** | **Yes — RAG + LLM adapter** |
| Plain-English fault explanation | **No** | **Yes** |
| Knowledge base (manuals + runbooks) | **No** | **Yes — Chroma/pgvector** |
| **Work Order Management** | | |
| Work order auto-generation | **No** | **Yes** |
| CMMS integration (ServiceNow, SAP) | **No** | **Yes** |
| Field technician mobile workflow | Partial (basic TB mobile) | **Yes — Flutter + React PWA** |
| **Analytics & KPIs** | | |
| Single-device widget dashboards | Yes (TB UI) | Replaced by React frontend |
| Cross-site KPI rollup | **No** | **Yes — Executive Dashboard** |
| Energy cost anomaly calculation | **No** | **Yes** |
| MTTR / uptime analytics | **No** | **Yes** |
| **Frontend** | | |
| UI | ThingsBoard UI (visible to customers) | React 19 + Next.js 15 (fully branded) |
| Floor map with live BMS overlay | **No** | **Yes — Deck.gl + SVG** |
| Network topology + blast radius | **No** | **Yes — React Flow** |
| **Multi-Tenancy & Auth** | | |
| Basic multi-tenancy | Yes | Extended with finer-grained RBAC |
| 5-role RBAC | **No (3 roles only)** | **Yes** |
| **Deployment** | | |
| SaaS / cloud | Yes | Yes (Azure AKS) |
| On-premise / air-gapped | Yes | Yes (Llama 3 for LLM) |
| Edge inference | Partial (TB Edge syncs config) | Extended (ML models at edge) |

---

## Part 4 — What Platform 2 Is and Is Not

### It IS:
- A **full-stack IoT operations intelligence platform** that uses ThingsBoard CE as its hidden device connectivity and telemetry engine
- A **white-labelled product** — no customer ever sees ThingsBoard
- An **AI-first operations platform** — the Chat-to-Fix, anomaly detection, predictive maintenance, and GNN root cause are the actual product
- **BMS + NMS unified** — no competing platform does both under one roof with AI
- **Deployable on-premise for air-gapped environments** (government, hospitals, defence)

### It is NOT:
- A **traditional SCADA replacement** — it cannot run PID control loops, execute ladder logic, or be used for safety-instrumented systems (SIL)
- A **PLC programming environment** — you still need vendor tools (TIA Portal, Studio 5000) to program the PLC itself
- A **real-time control platform** (sub-10ms loop control) — it is an operations intelligence and monitoring platform
- **Trying to be ThingsBoard PE** — it uses ThingsBoard CE as a component and builds something ThingsBoard PE does not have (AI, Chat-to-Fix, work orders, GNN root cause)

### The honest positioning:

Platform 2 sits **above** SCADA and CMMS in the operations stack — it consumes data from them (via OPC-UA, Modbus, MQTT) and gives operators the AI intelligence layer they currently do not have. It does not replace the PLC or the SCADA HMI. It replaces the manual process of an operator reading alarm dashboards, calling an engineer, searching for the manual, and creating a ticket.

---

*This analysis was generated from the ThingsBoard 4.4.0-SNAPSHOT codebase and the Platform2_Architecture_React.md document.*
