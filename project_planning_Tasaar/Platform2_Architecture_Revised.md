

**PLATFORM 2**

IoT Operations Intelligence Platform

**Revised Architecture Document**

ThingsBoard CE as Internal Device Registry Layer

| Frontend Stack | Vue 3 \+ Nuxt — fully branded, ThingsBoard never visible to end user |
| :---: | :---- |
| **Backend Stack** | FastAPI microservices \+ Flutter mobile \+ PostgreSQL / TimescaleDB \+ Redis |
| **ThingsBoard CE Role** | Internal device registry \+ telemetry buffer only — exposed via REST API \+ Kafka |
| **LLM Backend** | Provider-agnostic adapter — Claude, GPT-4, Llama 3 / Ollama switchable at config |
| **AI / ML Stack** | Isolation Forest · LSTM predictive maintenance · GNN root cause · RAG Chat-to-Fix |
| **Protocol Bridge** | MQTT · SNMP · BACnet / Modbus · gRPC · REST · KNX → Kafka (unified JSON schema) |
| **Cloud** | Azure (MeitY empanelled) — Kubernetes, AKS, blob storage, managed PostgreSQL |
| **MVP Timeline** | 20 Days |

# **1\. Design Rationale — ThingsBoard as Internal Layer**

The core architectural decision is to use ThingsBoard Community Edition exclusively as an internal service — a hidden engine for device registry and telemetry buffering. Every customer-facing surface is owned and branded by your product. This separation provides three concrete benefits:

* Complete white-labelling — customers see your product name, your design system, your URLs. ThingsBoard is an implementation detail identical to PostgreSQL or Kafka.

* AI focus — your engineering time concentrates entirely on the anomaly detection, predictive maintenance, GNN root cause, and RAG Chat-to-Fix layers that constitute your actual IP and competitive moat.

* Commercial freedom — ThingsBoard CE is Apache 2.0 licensed. You can sell SaaS subscriptions or on-premise deployments derived from it without royalties, restrictions, or ThingsBoard's involvement.

| What ThingsBoard CE provides (free, Apache 2.0) Device registry and asset hierarchy · MQTT / CoAP / HTTP device ingestion · Rule chains for alarm routing and webhook triggers · Basic dashboard widgets (used internally, not exposed to customers) · Multi-tenant namespace isolation · REST API for device and telemetry queries · Kafka integration for real-time telemetry streaming |
| :---- |

| What you build (your IP — the actual product) Vue 3 / Nuxt branded console with floor maps, topology views, Chat-to-Fix panel, work order tracker · FastAPI AI microservices: anomaly detection, LSTM predictive model, GNN root cause, RAG pipeline · Provider-agnostic LLM adapter (Claude / GPT-4 / Llama 3 switchable) · Knowledge base (Chroma / pgvector \+ LangChain) · Mobile PWA for field technicians · Work order auto-generation and CMMS integrations |
| :---- |

# **2\. Full Platform Architecture**

The architecture is structured in six horizontal layers. ThingsBoard CE occupies Layer 2 only — all layers above and below it are custom-built services invisible to the end customer.

| Platform 2 — IoT Operations Intelligence | Architecture Overview |
| :---: |

| LAYER 6CustomerFrontend | Vue 3 \+ Nuxt — Fully branded console (zero ThingsBoard UI exposed) Floor Map View (SVG clickable device nodes \+ live BMS alert overlay) Network Topology View (NMS alarm cascade, blast radius diagram) LLM Chat-to-Fix Panel (streaming SSE, context-injected, plain-English) Alert Timeline (real-time WebSocket feed, severity-filtered) Predictive Work Order Tracker (priority queue, parts list, assignments) Executive Dashboard (energy trends, uptime, maintenance cost KPIs) Mobile PWA — field technicians access Chat-to-Fix \+ work orders on-site |
| :---: | :---- |

| LAYER 5AI / MLIntelligenceCore | Anomaly Detection — Isolation Forest per device class, rolling 30-day baseline, edge \+ cloud dual Predictive Maintenance — LSTM on vibration / current / temperature, 24-72hr ahead, 87% precision Root Cause Analysis — GNN topology graph, cascade trace in 8 seconds Chat-to-Fix — LangChain RAG \+ provider-agnostic LLM adapter (Claude / GPT-4 / Llama 3\) Work Order Engine — auto-populates CMMS with device ID, fault, parts, labour estimate Edge Inference — containerised anomaly models per site, sub-100ms, offline-resilient |
| :---: | :---- |

| LAYER 4KnowledgeBase | Chroma / pgvector vector store — device manuals, maintenance runbooks, vendor troubleshooting guides Historical fault-action pairs from ticketing system (incremental RAG training) Network topology maps, SLA documents, CLI command references LangChain retrieval chain — top-5 document retrieval injected as LLM context at inference time Continuously updated as field technicians log resolution outcomes |
| :---: | :---- |

| LAYER 3FastAPIBackendServices | AI Orchestration Service — routes telemetry events to anomaly, LSTM, GNN microservices RAG / LLM Service — manages retrieval pipeline and LLM provider adapter Work Order Service — generates and syncs work orders to CMMS / ServiceNow / Remedy Alert Service — enriches ThingsBoard alarm events with AI context, pushes via WebSocket to Vue frontend Auth & Tenant Service — JWT, RBAC, multi-tenant namespace isolation (wraps TB tenant model) Integration Gateway — REST \+ Kafka event bridge to external analytics / Platform 3 / SCADA ThingsBoard Adapter — abstracts all TB REST API \+ Kafka calls behind internal interfaces |
| :---: | :---- |

| LAYER 2ThingsBoardCE(Internal) | Device Registry — all BMS sensors and NMS devices registered with metadata (class, location, protocol, baseline) Telemetry Buffer — raw time-series ingestion from all device protocols, short-term storage Rule Chains — alarm trigger logic, webhook calls to FastAPI Alert Service on threshold breach Kafka Integration — publishes live telemetry stream (topic per device class) consumed by FastAPI AI services REST API — polled by FastAPI ThingsBoard Adapter for device metadata and historical telemetry HIDDEN from all customer-facing surfaces — no TB UI, no TB branding, no TB URLs exposed |
| :---: | :---- |

| LAYER 1Device \&ProtocolLayer | BMS: HVAC (temp, humidity, CO2, AHU), energy meters, occupancy (BLE/PIR), elevators, fire, access control NMS: Routers / switches (SNMP v1/v2c/v3, gRPC, CLI), BTS / RAN (KPI counters), servers (syslog, IPMI) NMS: Transmission links (NetFlow, TWAMP), UPS / generators, firewalls (auth events, traffic anomalies) Protocol Bridge: MQTT broker (BMS IoT) \+ SNMP trap collector \+ BACnet/IP \+ Modbus TCP/RTU \+ gRPC \+ REST Unified JSON event schema on Apache Kafka, partitioned by device class and site Edge Gateway per site: protocol translation, MQTT-to-Kafka bridge, OTA orchestration, offline buffer |
| :---: | :---- |

# **3\. ThingsBoard CE Integration Pattern**

ThingsBoard CE is accessed by your FastAPI backend through two channels simultaneously. Neither channel is ever called from the frontend — the Vue 3 / Nuxt layer only talks to your own FastAPI services.

## **3.1 Channel A — ThingsBoard REST API**

Used for structured queries and device management operations. The FastAPI ThingsBoard Adapter wraps all TB REST calls so the rest of your codebase has no direct ThingsBoard dependency.

| Operation | ThingsBoard REST Endpoint | Called By |
| ----- | ----- | ----- |
| Register new device | POST /api/device | Device Onboarding Service |
| Query device metadata | GET /api/device/{id} | AI Orchestration Service |
| Fetch historical telemetry | GET /api/plugins/telemetry/{id}/values/timeseries | LSTM / RAG Services |
| List devices by tenant | GET /api/tenant/devices | Auth & Tenant Service |
| Acknowledge alarm | POST /api/alarm/{id}/ack | Alert Service |
| Assign device to asset | POST /api/relation | Device Onboarding Service |

## **3.2 Channel B — ThingsBoard Kafka Integration**

Used for high-throughput real-time telemetry streaming. ThingsBoard publishes device telemetry events to Kafka topics partitioned by device class. Your FastAPI AI microservices consume these topics directly.

| Kafka Topic | Producer | Consumer |
| ----- | ----- | ----- |
| tb.telemetry.bms.hvac | ThingsBoard CE | Anomaly Detection Service (Isolation Forest scoring) |
| tb.telemetry.bms.energy | ThingsBoard CE | LSTM Predictive Model \+ Energy Dashboard aggregator |
| tb.telemetry.nms.network | ThingsBoard CE | GNN Root Cause Service \+ Anomaly Detection Service |
| tb.alarms.all | ThingsBoard CE | Alert Service — enriches with AI context, WebSocket push to Vue frontend |
| platform.faults.outbound | FastAPI Alert Service | External analytics / Platform 3 / SCADA via Integration Gateway |

| Key principle ThingsBoard rule chains call FastAPI webhooks (not the other way around) for alarm triggers. FastAPI is the system of record for all AI-enriched data. ThingsBoard is never the source of truth for anything the customer sees. |
| :---- |

# **4\. LLM Provider-Agnostic Adapter**

The Chat-to-Fix LLM layer is designed as a swappable adapter behind a single internal interface. The RAG pipeline, context injection, and streaming response logic are identical regardless of which LLM backend is active. Provider selection is a configuration value, not a code change.

| Provider | Deployment Mode | Latency Profile | Best Fit |
| ----- | ----- | ----- | ----- |
| Claude (Anthropic) | API / SaaS | Low (streaming) | Default for SaaS deployments — highest quality RAG responses |
| GPT-4 (OpenAI) | API / SaaS | Low (streaming) | Alternative SaaS — customer preference or cost-tiering |
| Llama 3 / Ollama | Self-hosted on MEC / on-premise | Medium (GPU-dependent) | On-premise deployments, air-gapped sites, data-sovereign requirements |
| Azure OpenAI | Azure managed API | Low (streaming) | Enterprise customers requiring Azure-only data residency (MeitY) |

The adapter interface exposes three methods only: stream\_chat(context, query) → AsyncIterator, embed(text) → vector, and health\_check() → bool. LangChain wraps the RAG retrieval and document injection before calling stream\_chat. Switching provider requires changing one environment variable: LLM\_PROVIDER=claude | openai | ollama | azure\_openai.

# **5\. End-to-End Data Flow**

## **5.1 Real-Time Fault Detection and Chat-to-Fix Flow**

| Step | Actor | Action |
| :---: | ----- | ----- |
| 1 | Device (MQTT/SNMP/BACnet) | Publishes telemetry — ThingsBoard CE ingests and writes to internal time-series store |
| 2 | ThingsBoard CE → Kafka | Streams telemetry event to topic tb.telemetry.{class} |
| 3 | Anomaly Detection Service | Consumes Kafka stream, scores against Isolation Forest baseline — flags 3.4σ deviation |
| 4 | Alert Service | Receives anomaly flag, queries TB REST API for device metadata, enriches alert, pushes via WebSocket to Vue frontend |
| 5 | Vue 3 Frontend | Alert appears on floor map / topology view with severity indicator. Operator clicks alert — Chat panel opens with device context pre-injected. |
| 6 | Operator | Types plain-English question: 'Why is HVAC floor 3 consuming 23% more power?' |
| 7 | RAG / LLM Service | Retrieves top-5 relevant documents from Chroma vector store. Injects device history (from TB REST), maintenance logs, retrieved docs into LLM context. |
| 8 | LLM Adapter | Streams specific, actionable resolution back to Vue chat panel via SSE in under 90 seconds |
| 9 | Work Order Service | Auto-generates work order (device ID, fault, steps, parts, labour estimate) — syncs to CMMS / ServiceNow |
| 10 | RAG Training Loop | Field technician logs resolution outcome in Mobile PWA — outcome appended to knowledge base as new fault-action pair |

## **5.2 Predictive Maintenance Flow**

| Step | Actor | Action |
| :---: | ----- | ----- |
| 1 | ThingsBoard Kafka | Streams vibration, current draw, temperature time-series for BMS equipment continuously |
| 2 | LSTM Service (daily batch) | Scores equipment health per device — predicts failure probability 24-72 hours ahead |
| 3 | Work Order Service | Auto-creates priority maintenance work order with parts list, skill level, repair window, safety prerequisites |
| 4 | Vue 3 Frontend | Work order appears in Facility Manager's predictive queue — review and approve before failure occurs |
| 5 | ERP / Procurement | Parts procurement codes pushed to SAP / Oracle via Integration Gateway — parts ordered automatically |

# **6\. Full Technology Stack**

| Layer | Technology | Role |
| ----- | ----- | ----- |
| **Customer Frontend** | Vue 3 \+ Nuxt | SSR/SSG branded console — floor maps, topology, chat panel, work orders |
| Mobile PWA | Vite PWA plugin | Field technician access — Chat-to-Fix \+ work orders on-site |
| State Management | Pinia | Reactive store for alerts, device state, chat sessions |
| Real-time Push | WebSocket (FastAPI) | Live alert feed and device telemetry to Vue frontend |
| LLM Streaming | SSE (Server-Sent Events) | Chat-to-Fix streaming response from LLM to browser |
| **API Layer** | FastAPI (Python) | All AI orchestration, auth, alert enrichment, work order services |
| RAG Pipeline | LangChain | Document retrieval, context injection, LLM adapter orchestration |
| Vector Store | Chroma / pgvector | Embedded device manuals, runbooks, fault-action pairs |
| Stream Processing | Apache Kafka | Telemetry bus — TB CE publishes, AI services consume |
| **Primary Database** | PostgreSQL \+ TimescaleDB | Device registry, work orders, audit log, KPI time-series |
| Cache / Session | Redis | Alert deduplication, session tokens, rate limiting |
| Device Registry (internal) | ThingsBoard CE | Device onboarding, protocol ingestion, alarm rule chains, Kafka publish |
| **Anomaly Detection** | Isolation Forest (scikit-learn) | Per-device-class unsupervised scorer on live Kafka stream |
| Predictive Maintenance | LSTM (PyTorch / TensorFlow) | 24-72hr failure forecast on vibration / current / temperature |
| Root Cause Analysis | GNN (PyTorch Geometric) | Topology graph cascade trace — identifies single root fault in 8s |
| LLM (swappable) | Claude / GPT-4 / Llama 3 / Azure OpenAI | Chat-to-Fix — provider-agnostic adapter, one config switch |
| **Cloud** | Azure (MeitY empanelled) | AKS (Kubernetes), Blob Storage, managed PostgreSQL |
| Containerisation | Docker \+ Kubernetes | All services containerised — horizontal auto-scaling per Kafka partition |
| Edge Gateway | Docker Compose (edge node per site) | Protocol translation, MQTT-to-Kafka, edge ML inference, offline buffer |
| Mobile Backend | Flutter | Native mobile app option alongside PWA for field technicians |

# **7\. Revised 20-Day MVP Build Plan**

The build plan is restructured to reflect ThingsBoard CE as a pre-configured internal service. Days 1-2 stand up TB CE as a black box. All remaining effort goes directly into your product layers.

| Days | Focus | Deliverables |
| :---: | ----- | ----- |
| **Days** | **Focus** | **Deliverables** |
| **1–2** | **ThingsBoard Setup** | TB CE Docker deployment. Device schema defined (class, location, protocol, baseline params). MQTT broker and SNMP collector configured. Kafka integration enabled and tested. BACnet/Modbus protocol normaliser connected. TB REST API verified from FastAPI. ThingsBoard Adapter service scaffolded. |
| **3–5** | **FastAPI Backend Core** | FastAPI project structure with all service modules. PostgreSQL \+ TimescaleDB schema (devices, work orders, alerts, audit). Redis setup. JWT auth \+ multi-tenant RBAC. WebSocket alert push endpoint. Kafka consumer scaffolding for AI services. Docker Compose full stack running locally. |
| **6–10** | **AI / ML Core** | Isolation Forest models per device class trained on synthetic 30-day baseline (generated from TB Kafka stream). LSTM predictive model (vibration \+ current \+ temperature features). GNN root cause model on test topology dataset. LangChain RAG pipeline with Chroma vector store indexed with 20 sample manuals and runbooks. LLM adapter with Claude \+ OpenAI \+ Ollama backends switchable via config. Streaming Chat-to-Fix endpoint (SSE) tested end-to-end. |
| **11–15** | **Vue 3 \+ Nuxt Frontend** | Nuxt project with design system (no ThingsBoard UI anywhere). Floor Map view (SVG device nodes, live BMS alert overlay via WebSocket). Network Topology view (NMS alarm cascade). Streaming LLM Chat-to-Fix panel with context pre-injection on alert click. Real-time Alert Timeline with severity filtering. Predictive Work Order Tracker (priority queue, parts list, assignment). Executive energy / uptime dashboard. Mobile PWA build via Vite PWA plugin. |
| **16–17** | **Integrations** | ServiceNow webhook connector for work order creation. Generic REST \+ Kafka outbound event bridge for Platform 3 / external analytics. MQTT device simulator generating 24hrs of realistic BMS \+ NMS telemetry with 3 injected fault scenarios (HVAC bearing wear, NMS cascade, motor pre-failure). Flutter mobile app work order view. |
| **18–19** | **Demo Hardening** | Full demo script execution: HVAC anomaly fires → operator chats → Chat-to-Fix resolves in 90s. NMS outage injected → GNN traces root cause in 8s → LLM explains blast radius. Predictive work order auto-created 36hrs before simulated motor failure. Load test at 10k events/min. White-label branding verified (zero ThingsBoard references visible anywhere). |
| **20** | **Pitch Rehearsal** | Full pitch run-through with live demo environment. Investor Q\&A preparation. Deployment documentation for SaaS and on-premise options. Architecture review against this document. |

# **8\. Deployment Models**

The same codebase supports three deployment configurations. ThingsBoard CE is containerised in all three — it is never a separate concern from the customer's point of view.

| Attribute | SaaS (Multi-Tenant) | Dedicated Cloud | On-Premise |
| ----- | ----- | ----- | ----- |
| Hosting | Your Azure AKS cluster | Customer's Azure subscription | Customer's own datacenter |
| ThingsBoard CE | Shared instance, namespace isolation | Dedicated instance per customer | Self-hosted Docker Compose |
| LLM Provider | Claude / GPT-4 (API) | Azure OpenAI (data residency) | Llama 3 / Ollama (air-gapped) |
| Pricing | Per-device / month SaaS | Per-device \+ cloud infra pass-through | One-time licence \+ annual AMC |
| Target Customers | Commercial buildings, SME facilities | Enterprise, large telcos | Government, hospitals, defence, PSUs |
| Data Sovereignty | Shared (your control) | Customer's Azure tenant | Fully on-premise, no cloud egress |

# **9\. Competitive Positioning**

| Capability | Platform 2 | AWS IoT | ThingsBoard PE | IBM Maximo | Azure IoT Hub |
| ----- | :---: | :---: | :---: | :---: | :---: |
| BMS \+ NMS unified | **Yes** | No | Partial | No | No |
| RAG Chat-to-Fix | **Yes** | No | No | No | No |
| Predictive maintenance | **LSTM (24-72hr)** | No | No | Rules only | No |
| GNN root cause | **Yes** | No | No | No | No |
| White-label SaaS / on-prem | **Yes** | No | PE licence required | Partial | No |
| Apache 2.0 base | **Yes (TB CE)** | No | Commercial | Commercial | Commercial |

| Defensible product gap No existing platform combines BMS \+ NMS telemetry unification with a RAG-powered Chat-to-Fix interface, LSTM predictive maintenance, and GNN root cause analysis under a single white-labelled SaaS or on-premise product. This combination, built on an Apache 2.0 base, is your moat. |
| :---- |

