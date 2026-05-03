# PLATFORM 2
## IoT Operations Intelligence Platform
### Revised Architecture — React Frontend Edition

> **Base document:** Platform2_Architecture_Revised.md  
> **Key change:** Vue 3 + Nuxt replaced with React 19 + Next.js 15 across all layers  
> **Date:** 2026-05-03

---

| Frontend Stack | **React 19 + Next.js 15** — fully branded, ThingsBoard never visible to end user |
|:---:|:---|
| **Backend Stack** | FastAPI microservices + Flutter mobile + PostgreSQL / TimescaleDB + Redis |
| **ThingsBoard CE Role** | Internal device registry + telemetry buffer only — exposed via REST API + Kafka |
| **LLM Backend** | Provider-agnostic adapter — Claude, GPT-4, Llama 3 / Ollama switchable at config |
| **AI / ML Stack** | Isolation Forest · LSTM predictive maintenance · GNN root cause · RAG Chat-to-Fix |
| **Protocol Bridge** | MQTT · SNMP · BACnet / Modbus · gRPC · REST · KNX → Kafka (unified JSON schema) |
| **Cloud** | Azure (MeitY empanelled) — Kubernetes, AKS, Blob Storage, managed PostgreSQL |
| **MVP Timeline** | 20 Days |

---

## 1. Design Rationale — ThingsBoard as Internal Layer

*(Unchanged from base document — the strategic decision remains identical.)*

ThingsBoard Community Edition is used exclusively as an internal, hidden service — a device registry and telemetry buffer. Every customer-facing surface is owned and branded by your product. The substitution of React + Next.js for Vue + Nuxt is a **frontend technology choice only**; the layered architecture, the ThingsBoard isolation boundary, and all backend services are unaffected.

**Why React + Next.js over Vue + Nuxt:**

| Dimension | Vue 3 + Nuxt | React 19 + Next.js 15 | Decision Driver |
|---|---|---|---|
| Ecosystem depth | Good | Largest in frontend | More libraries for SVG floor maps, graph visualization, data grids |
| AI/chat UI components | Limited | Vercel AI SDK, Copilot Kit | Native SSE streaming primitives align with Chat-to-Fix requirements |
| SSR / RSC | Nuxt SSR | Next.js App Router + React Server Components | RSC reduces client bundle for dashboard pages |
| Enterprise hiring | Moderate pool | Deepest talent pool | MVP speed and long-term team scaling |
| PWA support | Vite PWA plugin | next-pwa / Serwist | Equivalent capability |
| Animation / UX richness | Good | Framer Motion (mature) | Operator console needs fluid transitions |
| MeitY-aligned integrations | Neutral | Neutral | Neither has an advantage |

---

## 2. Full Platform Architecture

The architecture is structured in six horizontal layers. **ThingsBoard CE occupies Layer 2 only.** The customer-facing React frontend is Layer 6.

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 6 — Customer Frontend                                                        │
│  React 19 + Next.js 15 (App Router + RSC)                                          │
│  Fully branded console — zero ThingsBoard UI, zero ThingsBoard branding             │
│                                                                                     │
│  Floor Map View    │  Network Topology  │  Chat-to-Fix Panel  │  Work Orders        │
│  (SVG + Deck.gl)   │  (React Flow DAG)  │  (SSE streaming)    │  (TanStack Table)   │
│  Alert Timeline    │  Executive KPIs    │  Predictive Queue   │  Mobile PWA         │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        │  REST + WebSocket + SSE
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 5 — AI / ML Intelligence Core                                                │
│  Anomaly Detection (Isolation Forest) · Predictive Maintenance (LSTM)               │
│  Root Cause Analysis (GNN) · RAG Chat-to-Fix (LangChain + LLM Adapter)             │
│  Work Order Engine · Edge Inference (containerised, offline-resilient)              │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        │
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 4 — Knowledge Base                                                           │
│  Chroma / pgvector vector store · LangChain retrieval chain                        │
│  Device manuals · Runbooks · Fault-action pairs · Network topology maps            │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        │
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 3 — FastAPI Backend Services                                                 │
│  AI Orchestration · RAG/LLM Service · Work Order Service · Alert Service           │
│  Auth & Tenant Service · Integration Gateway · ThingsBoard Adapter                 │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        │  REST API + Kafka
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 2 — ThingsBoard CE (Internal — never exposed to customers)                  │
│  Device Registry · Telemetry Buffer · Rule Chains · Kafka Publisher · REST API     │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        │
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — Device & Protocol Layer                                                  │
│  BMS (HVAC, energy, occupancy, fire, access) · NMS (routers, BTS, servers, UPS)    │
│  Protocol Bridge: MQTT · SNMP · BACnet/Modbus · gRPC · REST                       │
│  Edge Gateway per site: protocol translation, offline buffer, edge ML              │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. React Frontend Architecture (Layer 6 — Detailed)

### 3.1 Technology Choices

| Concern | Library / Tool | Replaces | Rationale |
|---|---|---|---|
| Framework | **Next.js 15** (App Router) | Nuxt 3 | RSC, streaming SSR, file-based routing, built-in API routes |
| UI Runtime | **React 19** | Vue 3 | Concurrent rendering, use() hook for streaming |
| Component Library | **shadcn/ui** + Radix UI primitives | — | Unstyled, accessible, fully white-labelable |
| Styling | **Tailwind CSS v4** | — | Utility-first; design tokens map to brand colours |
| State — global | **Zustand** | Pinia | Lightweight, no boilerplate, works with RSC boundary |
| State — server/async | **TanStack Query v5** | — | Cache, refetch, real-time invalidation |
| Real-time alerts | **native WebSocket** (custom hook) | WebSocket | Direct; no extra library for a WebSocket endpoint |
| LLM streaming | **Vercel AI SDK** (`useChat`, SSE) | — | Purpose-built for streaming LLM responses; provider-agnostic |
| Floor map | **Deck.gl** + **react-map-gl** + custom SVG overlay | — | GPU-accelerated, clickable device nodes, live BMS overlay |
| Network topology | **React Flow** | — | DAG visualiser; alarm cascade and blast-radius diagrams |
| Charts / KPIs | **Recharts** + **ECharts for React** | — | Recharts for simple KPIs; ECharts for complex time-series |
| Data grids | **TanStack Table v8** | — | Virtualized, sortable, filterable work order and alert tables |
| Maps | **React Leaflet** | — | Geo-location views for multi-site deployments |
| Forms | **React Hook Form** + **Zod** | — | Type-safe validation with no re-render overhead |
| Animation | **Framer Motion** | — | Fluid panel transitions, alert badge animations |
| Icons | **Lucide React** | — | Consistent, tree-shakeable icon set |
| PWA | **Serwist** (next-pwa successor) | Vite PWA plugin | Service worker, offline support, push notifications |
| i18n | **next-intl** | vue-i18n / nuxt-i18n | RSC-compatible translation layer |
| Auth | **Auth.js v5** (NextAuth) | — | JWT session, RBAC role injection, SSO-ready |
| Testing | **Vitest** + **React Testing Library** + **Playwright** | — | Unit, integration, E2E |
| Bundler | **Turbopack** (built into Next.js 15) | Vite | Faster HMR in dev; production build via webpack 5 |

### 3.2 App Router Directory Structure

```
apps/web/                          ← Next.js 15 App Router root
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx         ← Branded login — no TB references
│   │   └── layout.tsx
│   ├── (dashboard)/
│   │   ├── layout.tsx             ← Shell: sidebar, topbar, WebSocket provider
│   │   ├── floor-map/
│   │   │   └── [siteId]/page.tsx  ← Floor Map View (Deck.gl + SVG)
│   │   ├── topology/
│   │   │   └── [siteId]/page.tsx  ← Network Topology View (React Flow)
│   │   ├── alerts/
│   │   │   └── page.tsx           ← Alert Timeline (real-time WebSocket feed)
│   │   ├── chat/
│   │   │   └── page.tsx           ← Chat-to-Fix Panel (Vercel AI SDK SSE)
│   │   ├── work-orders/
│   │   │   ├── page.tsx           ← Work Order Tracker (TanStack Table)
│   │   │   └── [id]/page.tsx      ← Work Order Detail
│   │   ├── predictive/
│   │   │   └── page.tsx           ← Predictive Maintenance Queue
│   │   └── executive/
│   │       └── page.tsx           ← Energy / Uptime / Cost KPI Dashboard
│   ├── api/
│   │   └── auth/[...nextauth]/    ← Auth.js route handler
│   └── layout.tsx                 ← Root layout (font, theme provider)
├── components/
│   ├── ui/                        ← shadcn/ui base components
│   ├── floor-map/                 ← Deck.gl canvas + SVG device nodes
│   ├── topology/                  ← React Flow graph components
│   ├── chat/                      ← Chat-to-Fix panel + streaming renderer
│   ├── alerts/                    ← Alert card, timeline, severity badges
│   ├── work-orders/               ← Table, form, status stepper
│   └── charts/                    ← Recharts + ECharts wrappers
├── lib/
│   ├── ws/                        ← WebSocket singleton + custom hooks
│   ├── api/                       ← TanStack Query hooks over FastAPI REST
│   ├── store/                     ← Zustand slices (alerts, devices, chat)
│   └── auth/                      ← Auth.js config + RBAC helpers
├── public/
│   └── site-maps/                 ← SVG floor plan assets per site
└── next.config.ts
```

### 3.3 Key View Implementations

#### Floor Map View
- **Deck.gl ScatterplotLayer** renders live device positions on a floor-plan image tile.
- An SVG overlay drawn in React components shows device icons colour-coded by alert severity (`green` / `amber` / `red`).
- Clicking a device node opens a side-panel with live telemetry sparklines (Recharts) and a "Chat about this device" button that pre-injects device context into the Chat-to-Fix panel.
- WebSocket `useAlerts(siteId)` hook subscribes to FastAPI `/ws/alerts/{siteId}` and patches Zustand alert store on every message.

#### Network Topology View
- **React Flow** renders the network DAG: routers → switches → servers → end-points.
- Nodes are coloured by alarm state consumed from the same Zustand alert store.
- A blast-radius panel shows which downstream nodes are affected by the selected fault.
- GNN root-cause result is highlighted as a pulsing node.

#### Chat-to-Fix Panel
```typescript
// lib/chat/useChatToFix.ts
import { useChat } from "ai/react";

export function useChatToFix(deviceCtx: DeviceContext) {
  return useChat({
    api: "/api/chat",           // Next.js route → proxies to FastAPI SSE
    initialMessages: [
      { role: "system", content: buildDeviceContext(deviceCtx) },
    ],
  });
}
```
- Vercel AI SDK `useChat` manages the SSE stream internally.
- The Next.js `/api/chat` route handler acts as a thin proxy to the FastAPI RAG/LLM Service, forwarding the JWT and device context.
- The response streams token-by-token into the chat bubble component via React's `use()` hook — no page reload, no polling.

#### Work Order Tracker
- TanStack Table with column sorting, multi-filter, and row grouping by site.
- Optimistic updates via TanStack Query `useMutation` — work order status changes reflect immediately in the UI before FastAPI confirms.
- Export to CSV and PDF via browser APIs.

---

## 4. ThingsBoard CE Integration Pattern

*(Unchanged — all TB integration is FastAPI-side. The React frontend never calls ThingsBoard directly.)*

### 4.1 Channel A — ThingsBoard REST API

| Operation | ThingsBoard REST Endpoint | Called By |
|---|---|---|
| Register new device | `POST /api/device` | Device Onboarding Service |
| Query device metadata | `GET /api/device/{id}` | AI Orchestration Service |
| Fetch historical telemetry | `GET /api/plugins/telemetry/{id}/values/timeseries` | LSTM / RAG Services |
| List devices by tenant | `GET /api/tenant/devices` | Auth & Tenant Service |
| Acknowledge alarm | `POST /api/alarm/{id}/ack` | Alert Service |
| Assign device to asset | `POST /api/relation` | Device Onboarding Service |

### 4.2 Channel B — ThingsBoard Kafka Integration

| Kafka Topic | Producer | Consumer |
|---|---|---|
| `tb.telemetry.bms.hvac` | ThingsBoard CE | Anomaly Detection Service (Isolation Forest) |
| `tb.telemetry.bms.energy` | ThingsBoard CE | LSTM Predictive Model + Energy aggregator |
| `tb.telemetry.nms.network` | ThingsBoard CE | GNN Root Cause + Anomaly Detection |
| `tb.alarms.all` | ThingsBoard CE | Alert Service → WebSocket → **React frontend** |
| `platform.faults.outbound` | FastAPI Alert Service | External analytics / Platform 3 / SCADA |

> **Key principle:** ThingsBoard rule chains call FastAPI webhooks for alarm triggers. FastAPI is the system of record for all AI-enriched data. The React frontend only ever talks to FastAPI endpoints — never to ThingsBoard.

---

## 5. LLM Provider-Agnostic Adapter

*(Unchanged — fully backend concern)*

| Provider | Deployment Mode | Best Fit |
|---|---|---|
| Claude (Anthropic) | API / SaaS | Default SaaS — highest quality RAG responses |
| GPT-4 (OpenAI) | API / SaaS | Alternative SaaS — customer preference or cost-tiering |
| Llama 3 / Ollama | Self-hosted MEC / on-premise | Air-gapped, data-sovereign deployments |
| Azure OpenAI | Azure managed API | Enterprise MeitY data-residency requirement |

**Vercel AI SDK on the React side** provides a provider-agnostic client surface — `useChat` and `useCompletion` work identically regardless of which LLM the FastAPI backend selects. The frontend does not know or care which model is active.

---

## 6. End-to-End Data Flow

### 6.1 Real-Time Fault Detection and Chat-to-Fix Flow

| Step | Actor | Action |
|:---:|---|---|
| 1 | Device (MQTT/SNMP/BACnet) | Publishes telemetry — ThingsBoard CE ingests and writes to internal time-series store |
| 2 | ThingsBoard CE → Kafka | Streams telemetry event to topic `tb.telemetry.{class}` |
| 3 | Anomaly Detection Service | Consumes Kafka stream, scores against Isolation Forest baseline — flags 3.4σ deviation |
| 4 | Alert Service | Receives anomaly flag, queries TB REST API for device metadata, enriches alert, pushes via WebSocket to **React frontend** |
| 5 | **React Frontend** | Alert appears on floor map / topology view with severity indicator. Operator clicks alert — Chat panel opens with device context pre-injected via `useChatToFix(deviceCtx)` |
| 6 | Operator | Types: *"Why is HVAC floor 3 consuming 23% more power?"* |
| 7 | RAG / LLM Service | Retrieves top-5 docs from Chroma. Injects device history (from TB REST), maintenance logs, retrieved docs into LLM context |
| 8 | LLM Adapter | Streams resolution back to React chat panel via SSE — rendered token-by-token via Vercel AI SDK in under 90 seconds |
| 9 | Work Order Service | Auto-generates work order (device ID, fault, steps, parts, labour estimate) — syncs to CMMS / ServiceNow |
| 10 | RAG Training Loop | Field technician logs resolution outcome in Mobile PWA — appended to knowledge base as new fault-action pair |

### 6.2 Predictive Maintenance Flow

| Step | Actor | Action |
|:---:|---|---|
| 1 | ThingsBoard Kafka | Streams vibration, current draw, temperature time-series continuously |
| 2 | LSTM Service (daily batch) | Scores equipment health — predicts failure 24-72 hours ahead |
| 3 | Work Order Service | Auto-creates priority maintenance work order with parts list, skill level, repair window |
| 4 | **React Frontend** | Work order appears in Facility Manager's predictive queue (TanStack Table) — review and approve before failure |
| 5 | ERP / Procurement | Parts procurement codes pushed to SAP / Oracle via Integration Gateway |

---

## 7. Full Technology Stack

| Layer | Technology | Role |
|---|---|---|
| **Customer Frontend** | **React 19 + Next.js 15** | SSR + RSC branded console — floor maps, topology, chat panel, work orders |
| Mobile PWA | **Serwist** (next-pwa) | Field technician access — Chat-to-Fix + work orders on-site |
| State Management | **Zustand** (global) + **TanStack Query v5** (server state) | Reactive store for alerts, device state, chat sessions |
| Real-time Push | **WebSocket** (native, custom hook) | Live alert feed and device telemetry to React frontend |
| LLM Streaming | **Vercel AI SDK** `useChat` (SSE) | Chat-to-Fix streaming response from LLM to browser |
| Floor Map | **Deck.gl** + **React Leaflet** + SVG overlay | GPU-accelerated device map with live BMS alert overlay |
| Network Topology | **React Flow** | NMS alarm cascade, blast-radius diagram, GNN root cause highlight |
| Charts | **Recharts** + **ECharts for React** | KPI sparklines, time-series energy trends, anomaly overlays |
| Data Grid | **TanStack Table v8** | Virtualized, sortable work order and alert tables |
| Component System | **shadcn/ui** + **Radix UI** + **Tailwind CSS v4** | Accessible, fully white-labelable UI primitives |
| Animation | **Framer Motion** | Panel transitions, alert badge pulse |
| Auth (frontend) | **Auth.js v5** (NextAuth) | JWT session, RBAC, SSO-ready |
| **API Layer** | **FastAPI** (Python) | All AI orchestration, auth, alert enrichment, work order services |
| RAG Pipeline | **LangChain** | Document retrieval, context injection, LLM adapter orchestration |
| Vector Store | **Chroma** / **pgvector** | Device manuals, runbooks, fault-action pairs |
| Stream Processing | **Apache Kafka** | Telemetry bus — TB CE publishes, AI services consume |
| **Primary Database** | **PostgreSQL + TimescaleDB** | Device registry, work orders, audit log, KPI time-series |
| Cache / Session | **Redis** | Alert deduplication, session tokens, rate limiting |
| Device Registry (internal) | **ThingsBoard CE** | Device onboarding, protocol ingestion, alarm rule chains, Kafka publish |
| **Anomaly Detection** | Isolation Forest (scikit-learn) | Per-device-class unsupervised scorer on live Kafka stream |
| Predictive Maintenance | LSTM (PyTorch / TensorFlow) | 24-72 hr failure forecast on vibration / current / temperature |
| Root Cause Analysis | GNN (PyTorch Geometric) | Topology graph cascade trace — identifies root fault in 8 s |
| LLM (swappable) | Claude / GPT-4 / Llama 3 / Azure OpenAI | Chat-to-Fix — provider-agnostic adapter, one config switch |
| **Cloud** | **Azure** (MeitY empanelled) | AKS (Kubernetes), Blob Storage, managed PostgreSQL |
| Containerisation | Docker + Kubernetes | All services containerised — horizontal auto-scaling per Kafka partition |
| Edge Gateway | Docker Compose (per-site) | Protocol translation, MQTT-to-Kafka, edge ML inference, offline buffer |
| Mobile Backend | **Flutter** | Native mobile app for field technicians alongside PWA |

---

## 8. Revised 20-Day MVP Build Plan

> The only structural change from the base plan is **Days 11–15**, where Vue 3 + Nuxt is replaced with React 19 + Next.js 15. All other days and deliverables are identical.

### Days 1–2 — ThingsBoard Setup

**Goal:** TB CE running as a silent internal service with all integration points verified.

| Task | Detail |
|---|---|
| Deploy TB CE | Docker Compose on a VM / AKS node. No public URL — internal only. |
| Define device schema | Device classes: `bms.hvac`, `bms.energy`, `nms.network`, `nms.server`. Attributes: `class`, `site_id`, `location`, `protocol`, `baseline_params`. |
| Configure MQTT broker | ThingsBoard MQTT on port 1883 (internal). BACnet/Modbus normaliser to MQTT. |
| Enable Kafka integration | TB CE → Kafka rule chain action verified. Topics `tb.telemetry.bms.hvac`, `tb.telemetry.bms.energy`, `tb.telemetry.nms.network`, `tb.alarms.all` receiving data. |
| Verify REST API | FastAPI ThingsBoard Adapter scaffold. Curl-test all six REST operations from the adapter. |
| SNMP collector | SNMP trap collector → MQTT bridge tested with a simulated NMS device. |

**Exit criteria:** Kafka consumer script prints live telemetry from a simulated HVAC device.

---

### Days 3–5 — FastAPI Backend Core

**Goal:** All FastAPI services scaffolded and running locally with Docker Compose.

| Task | Detail |
|---|---|
| Project structure | Monorepo: `apps/api/` (FastAPI), `apps/web/` (Next.js), `services/` (AI microservices). |
| PostgreSQL + TimescaleDB schema | Tables: `devices`, `alerts`, `work_orders`, `alert_ai_context`, `rag_training_pairs`, `audit_log`. TimescaleDB hypertable on `telemetry_kv(device_id, ts)`. |
| Redis setup | Alert deduplication key: `alert:{device_id}:{fault_type}`. Session token store. Rate limiter middleware. |
| JWT auth + RBAC | FastAPI dependency: `Depends(get_current_user)`. Roles: `SYSTEM_ADMIN`, `FACILITY_MANAGER`, `FIELD_TECHNICIAN`, `EXECUTIVE`. |
| WebSocket alert endpoint | `GET /ws/alerts/{site_id}` — broadcasts enriched alert JSON to all connected React clients for that site. |
| Kafka consumer scaffolding | `aiokafka` consumers for each topic. Dispatch to anomaly / LSTM / GNN services via internal HTTP or direct Python call. |
| ThingsBoard Adapter | `TBAdapter` class wrapping all TB REST calls. Injected as FastAPI dependency. Rest of codebase has zero direct TB dependency. |
| Docker Compose (local) | Services: `tb-ce`, `postgres`, `redis`, `kafka`, `zookeeper`, `api`, `web`. Single `docker-compose up` starts full stack. |

**Exit criteria:** `POST /api/auth/login` returns JWT. WebSocket echo test with Postman succeeds.

---

### Days 6–10 — AI / ML Core

**Goal:** All four AI/ML capabilities working end-to-end on synthetic data.

| Task | Detail |
|---|---|
| Isolation Forest (anomaly) | scikit-learn model trained on 30-day synthetic baseline per device class. Kafka consumer scores each event; anomalies published to Alert Service internal queue. Threshold: 3.4σ. |
| LSTM (predictive maintenance) | PyTorch model on vibration + current + temperature sequences. Daily batch job (Celery). Output: `{device_id, failure_probability, predicted_failure_window}`. |
| GNN root cause | PyTorch Geometric on topology adjacency matrix. Input: active alarm set. Output: root fault node + cascade path in ≤ 8 s. Tested on 3 synthetic NMS fault scenarios. |
| LangChain RAG pipeline | Chroma vector store. Ingest 20 sample device manuals + runbooks. LangChain `RetrievalQA` chain: top-5 doc retrieval → context injection → LLM call. |
| LLM adapter | `BaseLLMAdapter` interface: `stream_chat()`, `embed()`, `health_check()`. Implementations: `ClaudeAdapter`, `OpenAIAdapter`, `OllamaAdapter`, `AzureOpenAIAdapter`. Switch via `LLM_PROVIDER` env var. |
| SSE streaming endpoint | `GET /api/chat/stream` — FastAPI `StreamingResponse` wrapping LLM adapter `stream_chat()`. Tested with curl. |
| Alert enrichment | Alert Service: receives anomaly flag, calls TB Adapter for device metadata, calls GNN for root cause, constructs enriched alert JSON, pushes to WebSocket + stores in PostgreSQL. |
| Work Order auto-generation | Work Order Service: on `CRITICAL` alert or LSTM high-probability event, auto-generates work order record. ServiceNow webhook stub. |

**Exit criteria:** End-to-end test: simulated HVAC temperature spike → Isolation Forest flags anomaly → Alert Service enriches → Chat-to-Fix returns actionable resolution from Claude in under 90 s.

---

### Days 11–15 — React 19 + Next.js 15 Frontend

**Goal:** Fully branded, white-label React console with all five key views operational.

#### Day 11 — Project Scaffold + Design System

| Task | Detail |
|---|---|
| Next.js 15 init | `npx create-next-app@latest --app --typescript --tailwind`. Turbopack enabled for dev. |
| shadcn/ui setup | `npx shadcn@latest init`. Theme tokens mapped to brand colours. Radius, font, and spacing defined as Tailwind CSS variables. |
| Auth.js v5 | JWT session. Login page — fully branded, zero ThingsBoard reference. RBAC role injected into session. |
| Layout shell | App Router layout: collapsible sidebar (site selector, nav links), topbar (tenant name, user avatar, notification bell). Responsive (desktop + tablet). |
| Zustand store | Slices: `useAlertStore`, `useDeviceStore`, `useChatStore`, `useWorkOrderStore`. Persist alert count to localStorage for notification badge across reloads. |
| TanStack Query provider | `QueryClientProvider` in root layout. Global `staleTime: 30_000`. |
| WebSocket hook | `useAlertSocket(siteId)` — singleton WebSocket to FastAPI `/ws/alerts/{siteId}`. On message: dispatches to `useAlertStore`. Reconnects with exponential backoff. |

#### Day 12 — Floor Map View + Network Topology View

| Task | Detail |
|---|---|
| Floor Map | Deck.gl `DeckGL` canvas on floor-plan PNG tile. `ScatterplotLayer` for device positions. SVG overlay for device icons (colour = alert severity). Click handler opens device side-panel. |
| Device side-panel | `shadcn/ui Sheet`. Shows: device name, class, site, last 24 h telemetry sparkline (Recharts `LineChart`), active alarms list, "Chat about this device" CTA. |
| Network Topology | React Flow `ReactFlow` canvas. Nodes fetched from FastAPI `GET /api/topology/{siteId}`. Edge colours = link health. Node colours = alarm severity. Minimap + controls. |
| Blast-radius panel | On node click: FastAPI `GET /api/rootcause/{deviceId}` → highlight root cause node (pulsing Framer Motion animation) + downstream affected nodes. |
| Alarm overlay | Both views subscribe to same `useAlertStore` — alert changes update node colours without re-fetch. |

#### Day 13 — Alert Timeline + Chat-to-Fix Panel

| Task | Detail |
|---|---|
| Alert Timeline | TanStack Table: columns (severity, device, site, fault type, time, status, actions). Severity filter (CRITICAL / MAJOR / MINOR). Real-time row insertion from `useAlertStore` — no page refresh. Acknowledge action → `POST /api/alerts/{id}/ack`. |
| Chat-to-Fix Panel | Full-width slide-over (`shadcn/ui Sheet`). `useChatToFix(deviceCtx)` hook (Vercel AI SDK `useChat`). Next.js `/api/chat` route handler proxies to FastAPI SSE endpoint. Markdown rendering for code blocks and numbered steps (react-markdown). Streaming token display. |
| Context injection | When opened from a device click, `deviceCtx` auto-populates with device ID, class, site, last anomaly summary, active alarms — injected as system message before operator types. |
| Chat history | Stored in `useChatStore` (Zustand). Session persisted in Redis on FastAPI side. |

#### Day 14 — Work Orders + Predictive Queue + Executive Dashboard

| Task | Detail |
|---|---|
| Work Order Tracker | TanStack Table with grouping by site. Columns: priority, device, fault, steps, parts, assignee, status, due date. Optimistic status update via TanStack Query `useMutation`. CSV export. |
| Work Order Detail | `/work-orders/[id]` page. Shows full fault description, step-by-step resolution (from LLM), parts list with procurement codes, safety prerequisites. Approve / reject / reassign actions. |
| Predictive Queue | Separate tab — LSTM-generated work orders sorted by `failure_probability` desc. 24/48/72 hr failure windows colour-coded. |
| Executive Dashboard | KPI cards: total devices online, active alarms by severity, MTTR this month, energy anomaly cost estimate. ECharts `LineChart` for 30-day energy trend. `BarChart` for alarm frequency by site. Recharts `RadialBarChart` for uptime by device class. All data from FastAPI REST — SSR via Next.js Server Components for initial render. |

#### Day 15 — Mobile PWA + Polish + White-Label Verification

| Task | Detail |
|---|---|
| PWA setup | Serwist `next-pwa` config. Service worker caches shell, fonts, and icon assets. Push notification manifest. |
| Mobile-optimised views | Work order list and detail fully usable on 375 px width. Chat-to-Fix panel full-screen on mobile. Alert timeline card layout on small screens. |
| White-label audit | Grep entire Next.js codebase for `thingsboard`, `ThingsBoard`, `tb_`, port `8080` (TB direct). Zero occurrences allowed. All API calls go to FastAPI base URL. Product name, logo, favicon, `<title>`, error pages — all branded. |
| Loading states | Skeleton screens (shadcn/ui `Skeleton`) on all data-fetching routes. |
| Error boundaries | React `ErrorBoundary` on each major view. Friendly error UI — never exposes stack trace to operator. |
| Accessibility | All interactive elements keyboard-navigable. Colour contrast WCAG 2.1 AA on severity palette. |

---

### Days 16–17 — Integrations

*(Identical to base plan)*

| Task | Detail |
|---|---|
| ServiceNow connector | Work Order Service webhook → ServiceNow `POST /api/now/table/incident`. Map Platform 2 fields to ServiceNow schema. |
| Integration Gateway | Generic REST + Kafka outbound bridge for Platform 3 / external analytics / SCADA. |
| Device simulator | MQTT simulator generating 24 hrs of realistic BMS + NMS telemetry. Three injected fault scenarios: HVAC bearing wear, NMS cascade failure, motor pre-failure. |
| Flutter mobile | Native work order list + Chat-to-Fix view. Calls same FastAPI endpoints as React PWA. |

---

### Days 18–19 — Demo Hardening

| Task | Detail |
|---|---|
| Full demo script | HVAC anomaly fires → React alert overlay → operator opens Chat-to-Fix → streaming resolution in 90 s. NMS outage injected → GNN traces root cause in 8 s → LLM explains blast radius on topology view. Predictive work order auto-created 36 hrs before simulated motor failure. |
| Load test | k6 / Locust: 10,000 events/min from simulator. React frontend showing live updates without dropped frames (Chrome DevTools Performance). |
| White-label final check | Run automated Playwright test: crawl all pages, screenshot every view, assert zero ThingsBoard references in DOM, network requests, or page titles. |
| Security pass | JWT expiry handling. RBAC: FIELD_TECHNICIAN cannot access Executive Dashboard (403). Rate limiting on `/api/chat` (10 req/min per user). HTTPS enforced. |

---

### Day 20 — Pitch Rehearsal

| Task | Detail |
|---|---|
| Live demo environment | AKS staging cluster with all services healthy. 15-minute demo script rehearsed. |
| Investor Q&A prep | ThingsBoard CE licensing (Apache 2.0 — confirmed no restrictions). AI model cost per 1,000 devices/month. On-premise deployment SLA. |
| Documentation | README per service. Docker Compose one-liner start. Deployment guide for SaaS + on-premise. Architecture diagram exported from this document. |
| Architecture review | Verify this document matches the running system exactly. |

---

## 9. Implementation Plan — Execution Details

### Repository Structure

```
platform2/
├── apps/
│   ├── web/                    ← Next.js 15 (this document, Days 11–15)
│   └── api/                    ← FastAPI monolith (Days 3–5)
├── services/
│   ├── anomaly/                ← Isolation Forest service
│   ├── predictive/             ← LSTM service
│   ├── rootcause/              ← GNN service
│   ├── rag/                    ← LangChain + LLM adapter
│   └── workorder/              ← Work Order service
├── infra/
│   ├── docker/                 ← Docker Compose (local dev)
│   ├── k8s/                    ← AKS Helm charts
│   └── edge/                   ← Edge gateway Docker Compose
├── tools/
│   ├── simulator/              ← MQTT device simulator
│   └── tb-setup/               ← ThingsBoard CE bootstrap scripts
└── docs/
    └── Platform2_Architecture_React.md   ← this file
```

### Environment Variables (React / Next.js)

```bash
# apps/web/.env.local
NEXT_PUBLIC_API_URL=https://api.platform2.internal    # FastAPI base URL
NEXT_PUBLIC_WS_URL=wss://api.platform2.internal       # WebSocket base URL
NEXTAUTH_URL=https://app.platform2.internal
NEXTAUTH_SECRET=<32-byte random>
# No ThingsBoard URL — frontend never calls TB directly
```

### Docker Compose (local, `infra/docker/docker-compose.yml`)

```yaml
services:
  tb-ce:
    image: thingsboard/tb-postgres:latest
    ports: ["9090:9090"]          # internal port only — not published to host
    networks: [internal]

  postgres:
    image: timescale/timescaledb:latest-pg16
    ports: ["5432:5432"]

  redis:
    image: valkey/valkey:7.2
    ports: ["6379:6379"]

  kafka:
    image: confluentinc/cp-kafka:7.6.0
    ports: ["9092:9092"]

  api:
    build: apps/api
    ports: ["8000:8000"]
    environment:
      TB_URL: http://tb-ce:9090
      KAFKA_BROKERS: kafka:9092
      LLM_PROVIDER: claude

  web:
    build: apps/web
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_URL: http://api:8000
      NEXT_PUBLIC_WS_URL: ws://api:8000

networks:
  internal:
    driver: bridge
```

### FastAPI → React API Contract

All FastAPI endpoints consumed by React:

| Method | Endpoint | React Consumer |
|---|---|---|
| `POST` | `/api/auth/login` | Auth.js credentials provider |
| `GET` | `/api/alerts?site_id=` | `useAlertStore` initial hydration |
| `WS` | `/ws/alerts/{site_id}` | `useAlertSocket` hook |
| `GET` | `/api/devices?site_id=` | Floor map + topology data fetch |
| `GET` | `/api/topology/{site_id}` | React Flow graph |
| `GET` | `/api/rootcause/{device_id}` | Blast-radius panel |
| `POST` | `/api/alerts/{id}/ack` | Alert Timeline action |
| `GET` | `/api/work-orders` | Work Order Tracker |
| `POST` | `/api/work-orders/{id}/status` | Work order status mutation |
| `GET` | `/api/kpis?site_id=&range=30d` | Executive Dashboard |
| `POST` | `/api/chat` (SSE) | Chat-to-Fix (proxied via Next.js `/api/chat`) |

---

## 10. Deployment Models

*(Unchanged from base plan — all three models apply equally to the React frontend)*

| Attribute | SaaS (Multi-Tenant) | Dedicated Cloud | On-Premise |
|---|---|---|---|
| Hosting | Your Azure AKS cluster | Customer's Azure subscription | Customer's own datacenter |
| ThingsBoard CE | Shared instance, namespace isolation | Dedicated instance per customer | Self-hosted Docker Compose |
| LLM Provider | Claude / GPT-4 (API) | Azure OpenAI (data residency) | Llama 3 / Ollama (air-gapped) |
| React Frontend | Served from AKS ingress | Same AKS, custom domain | Docker container on-premise |
| Pricing | Per-device / month SaaS | Per-device + cloud infra pass-through | One-time licence + annual AMC |
| Target Customers | Commercial buildings, SME facilities | Enterprise, large telcos | Government, hospitals, defence, PSUs |
| Data Sovereignty | Shared (your control) | Customer's Azure tenant | Fully on-premise, no cloud egress |

---

## 11. Competitive Positioning

*(Unchanged — the frontend technology choice does not affect competitive positioning)*

| Capability | Platform 2 | AWS IoT | ThingsBoard PE | IBM Maximo | Azure IoT Hub |
|---|:---:|:---:|:---:|:---:|:---:|
| BMS + NMS unified | **Yes** | No | Partial | No | No |
| RAG Chat-to-Fix | **Yes** | No | No | No | No |
| Predictive maintenance | **LSTM (24-72 hr)** | No | No | Rules only | No |
| GNN root cause | **Yes** | No | No | No | No |
| White-label SaaS / on-prem | **Yes** | No | PE licence required | Partial | No |
| Apache 2.0 base | **Yes (TB CE)** | No | Commercial | Commercial | Commercial |

> **Defensible product gap:** No existing platform combines BMS + NMS telemetry unification with a RAG-powered Chat-to-Fix interface, LSTM predictive maintenance, and GNN root cause analysis under a single white-labelled SaaS or on-premise product. This combination, built on an Apache 2.0 base, is your moat.

---

## 12. Risk Register & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|:---:|:---:|---|
| Next.js App Router learning curve for team | Medium | Medium | Use Next.js 15 official docs + shadcn/ui example patterns. RSC used conservatively — only for SSR KPI pages. |
| Vercel AI SDK SSE breaks on custom FastAPI proxy | Low | High | Test `/api/chat` proxy on Day 11. Fallback: remove proxy, call FastAPI SSE directly from browser with CORS. |
| Deck.gl GPU rendering on low-end operator laptops | Medium | Medium | Progressive enhancement: fallback to SVG-only floor map if WebGL unavailable. |
| React Flow performance on 500+ node topology | Low | Medium | Enable React Flow `nodesDraggable=false`, `elementsSelectable=false` in read-only mode. Use `miniMapNodeColor` instead of full node rendering in minimap. |
| WhatsApp/mobile PWA push notification gaps on iOS | Medium | Low | Flutter native app covers iOS. PWA notifications are Android/desktop Chrome primary. |
| ThingsBoard Kafka topic format changes on TB upgrade | Low | High | ThingsBoard Adapter service is the only consumer of raw TB Kafka events. Buffer transform in adapter — rest of system is insulated. |

---

*This document supersedes the Vue/Nuxt sections of Platform2_Architecture_Revised.md. All other architectural decisions remain identical.*

*Generated: 2026-05-03*
