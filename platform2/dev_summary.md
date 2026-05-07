  ---
  Phase 1 — Infrastructure & Wiring (Days 1–2)                                                                                                                                         
                                                                                                                                                                                       
  docker-compose.yml                                                                                                                                                                   
                                                                                                                                                                                       
  Defines the entire 7-service stack: ThingsBoard CE (device registry + rule engine + UI), Apache Kafka + Zookeeper (message bus), TimescaleDB/PostgreSQL (time-series + relational    
  DB), Redis (cache), ChromaDB (vector store), FastAPI (AI services), and the Simulator (demo-only profile). All services share a bridge network (platform2-net) with named volumes for
   persistence.                                                                                                                                                                        
                                                            
  .env.example                                                                                                                                                                         
  
  Documents every environment variable the stack needs — API keys, DB passwords, LLM provider selection, Kafka topics, LSTM thresholds, rate limits — with comments explaining each    
  one. The operator copies this to .env and fills in secrets before first boot.
                                                                                                                                                                                       
  scripts/init-multiple-dbs.sh                              

  PostgreSQL init script that runs on first container start. Creates two databases (thingsboard for the device registry, platform2 for Vantage NMS) and a dedicated p2 user with the   
  TimescaleDB extension enabled.
                                                                                                                                                                                       
  scripts/onboard_devices.py                                

  Bulk device registration script. Reads a CSV of device names/classes/locations, calls the ThingsBoard REST API to create devices, assigns them to an asset hierarchy (Site → BMS /   
  NMS → device type), and writes MQTT access tokens to credentials.csv for the simulator.
                                                                                                                                                                                       
  scripts/devices_sample.csv                                                                                                                                                           
  
  24 pre-defined sample devices spanning all device classes (HVAC, energy, network, infra, occupancy, elevator, fire). Used as a starting point for onboarding.                        
                                                            
  rule_chains/telemetry_routing.json                                                                                                                                                   
                                                            
  ThingsBoard rule chain that reads the device_class attribute on each incoming telemetry message and routes it to the correct Kafka topic (platform2.hvac, platform2.energy,          
  platform2.network, platform2.infra, platform2.other). The FastAPI Kafka consumer subscribes to all five.
                                                                                                                                                                                       
  rule_chains/alarm_webhook.json                            

  ThingsBoard rule chain that fires on every alarm lifecycle event (created, updated, cleared). Sends a POST to /webhook/alarm and /webhook/cascade on the FastAPI service so AI       
  enrichment runs immediately without polling.
                                                                                                                                                                                       
  fastapi/config.py                                         

  Single Settings class using pydantic-settings. Reads every config value from environment variables with typed defaults. All other modules import from here — no inline               
  os.environ.get() anywhere in the codebase.
                                                                                                                                                                                       
  fastapi/db/postgres.py                                    

  SQLAlchemy async engine setup and all four ORM models:                                                                                                                               
  - WorkOrder — maintenance tasks with priority, status, steps, parts, labour hours, due date
  - AuditLog — immutable event log for every system action (alarm received, WO created, chat query, cascade analyzed)                                                                  
  - EquipmentHealth — TimescaleDB hypertable storing LSTM health scores per device per timestamp                     
  - AnomalyScore — TimescaleDB hypertable storing Isolation Forest scores per device per timestamp                                                                                     
                                                                                                                                                                                       
  fastapi/db/migrations/env.py                                                                                                                                                         
                                                                                                                                                                                       
  Alembic async migration environment. Configures SQLAlchemy async engine for migration runs so schema changes can be applied without running the full application.                    
                                                            
  fastapi/db/migrations/versions/001_initial_schema.py                                                                                                                                 
                                                            
  First (and only) Alembic migration. Creates all four tables with correct column types (UUID PKs, TIMESTAMPTZ, JSONB) and converts equipment_health and anomaly_scores to TimescaleDB 
  hypertables with 1-day chunk intervals.                   
                                                                                                                                                                                       
  fastapi/db/alembic.ini                                    

  Alembic configuration pointing to the async migration environment.

  fastapi/services/tb_client.py                                                                                                                                                        
  
  Async HTTP wrapper around the ThingsBoard REST API. Handles JWT login, token refresh on 401, and 3-attempt exponential backoff (1s → 2s → 4s) on every request. Exposes:             
  get_device(), get_device_attributes(), get_latest_telemetry(), get_telemetry() (historical with time range), get_alarms(), create_alarm(), update_alarm_attributes(),
  set_device_server_attributes(). Module-level singleton via get_tb_client().                                                                                                          
                                                            
  fastapi/requirements.txt

  All Python dependencies pinned to exact versions — FastAPI, SQLAlchemy, aiokafka, LangChain, ChromaDB, scikit-learn, PyTorch, Anthropic SDK, OpenAI SDK, and all supporting          
  libraries.
                                                                                                                                                                                       
  fastapi/Dockerfile                                        

  Python 3.11-slim image. Installs pinned requirements, copies source, runs Alembic migrations then starts Uvicorn.                                                                    
  
  ---                                                                                                                                                                                  
  Phase 2 — FastAPI Foundation (Days 3–4)                   
                                                                                                                                                                                       
  fastapi/main.py
                                                                                                                                                                                       
  Application entry point. The lifespan async context manager starts up in order: PostgreSQL connection check → Redis ping → ChromaDB heartbeat → Kafka consumer background task →     
  APScheduler (predictive batch + topology rebuild). Registers all routers, adds CORS middleware, and installs a global exception handler that returns structured {error, detail, ts}
  JSON for all unhandled exceptions. Also hosts debug endpoints (/debug/run-predictive, /debug/rebuild-topology, /debug/train-gnn).                                                    
                                                            
  fastapi/models/schemas.py                                                                                                                                                            
  
  All Pydantic v2 models in one file, grouped by domain:                                                                                                                               
  - Work order models: WorkOrderCreate, WorkOrderResponse, WorkOrderList, WorkOrderStatusUpdate (with valid transition map)
  - Webhook models: AlarmWebhookPayload, CascadeWebhookPayload, WebhookAck                                                                                                             
  - Chat models: ChatRequest, WidgetContext                               
  - AI result models: AnomalyResult, PredictiveResult, RootCauseResult                                                                                                                 
  - Health models: HealthResponse, ErrorResponse            
                                                                                                                                                                                       
  fastapi/routers/health.py                                 
                                                                                                                                                                                       
  GET /health — runs parallel async checks against all 6 downstream services (PostgreSQL, Redis, ChromaDB, Kafka, ThingsBoard, LLM provider) and returns a structured HealthResponse   
  with per-service status, loaded model list, and overall healthy | degraded | unhealthy status.
                                                                                                                                                                                       
  fastapi/routers/webhook.py                                                                                                                                                           
  
  POST /webhook/alarm — receives ThingsBoard alarm events. Uses Redis SET NX (60s TTL) for dedup, fires _enrich_alarm_bg background task (fetches telemetry, scores with Isolation     
  Forest, writes ai_anomaly_score / ai_sigma / ai_explanation back to the device as server attributes). Feeds the in-process cascade accumulator.
                                                                                                                                                                                       
  POST /webhook/cascade — feeds the same cascade accumulator directly. When the buffer hits the configured threshold within the time window, fires _analyze_cascade_bg which collects  
  per-device anomaly scores, calls the GNN service, writes root cause enrichment to all cascade alarms, and writes an alarm_cascade_analyzed AuditLog entry (used later for GNN
  training).                                                                                                                                                                           
                                                            
  fastapi/routers/workorders.py

  Full CRUD for the work order queue:                                                                                                                                                  
  - GET /workorders — paginated list with filters for entity_id, status, priority, sort order
  - POST /workorders — create work order, writes AuditLog entry                                                                                                                        
  - GET /workorders/{id} — single work order                   
  - PATCH /workorders/{id}/status — state machine transition with STATUS_TRANSITIONS validation; only valid transitions (e.g. open→acknowledged, acknowledged→in_progress) are accepted
                                                                                                                                                                                       
  Stubs (replaced in later phases)                                                                                                                                                     
                                                                                                                                                                                       
  - services/anomaly.py — neutral AnomalyResult placeholder                                                                                                                            
  - services/gnn.py — heuristic fallback placeholder                                                                                                                                   
  - services/topology.py — empty DiGraph placeholder                                                                                                                                   
  - services/predictive_batch.py — no-op placeholder                                                                                                                                   
  - consumers/telemetry.py — TelemetryConsumer class with reconnect loop but no processing logic
                                                                                                                                                                                       
  ---                                                       
  Phase 3 — RAG + Conversational AI (Days 5–9)                                                                                                                                         
                                                                                                                                                                                       
  fastapi/services/llm_adapter.py
                                                                                                                                                                                       
  Abstract LLMAdapter base class with three concrete implementations:                                                                                                                  
  - ClaudeAdapter — Anthropic async SDK, claude-sonnet-4-20250514, streaming via stream_chat(), no native embedding (delegates to fallback)
  - OpenAIAdapter — OpenAI async SDK, gpt-4o for chat, text-embedding-3-small for embeddings                                                                                           
  - OllamaAdapter — raw httpx streaming to Ollama REST, llama3 model, local embedding endpoint
                                                                                                                                                                                       
  _EmbedFallback class pairs Claude chat with Ollama embeddings (since Claude has no embedding API). get_llm_adapter() reads LLM_PROVIDER env var and returns the right implementation.
                                                                                                                                                                                       
  fastapi/services/rag.py                                                                                                                                                              
                                                                                                                                                                                       
  LangChain + ChromaDB retrieval pipeline:                  
  - retrieve_context(query, device_class, document_type, k=5) — searches ChromaDB with a where metadata filter so HVAC queries only retrieve HVAC documents
  - format_rag_context() — formats retrieved chunks as numbered sections for the prompt                                                                                                
  - add_fault_resolution(question, answer, entity_id, device_class) — indexes successful chat interactions back into ChromaDB so future queries benefit from past resolutions
  - add_documents_from_text() — ingests raw text with metadata                                                                                                                         
  - collection_count() — returns total indexed documents      
                                                                                                                                                                                       
  fastapi/services/context_builder.py                                                                                                                                                  
                                                                                                                                                                                       
  Assembles device context for each chat request by fetching from ThingsBoard: latest telemetry values, 48-hour historical trends (min/max/mean/trend direction per key), active alarms
   (up to 5), and device attributes (name, class, floor, zone, firmware). Results are cached in Redis for 30 seconds per device to avoid hammering ThingsBoard on rapid follow-up
  questions.                                                                                                                                                                           
                                                            
  fastapi/services/prompt_builder.py

  Builds the system prompt from assembled context and RAG documents. Instructs the LLM to structure its response in 5 sections: Root Cause → Immediate Action → Permanent Fix → Parts  
  Required → Estimated Time. Includes a schema for an optional embedded ```work_order``` JSON block the LLM can emit when it recommends a maintenance task. Also provides
  extract_work_order_json() (regex parser) and strip_work_order_block() (removes the raw block before streaming to the widget).                                                        
                                                            
  fastapi/routers/chat.py                                                                                                                                                              
  
  POST /chat — the primary operator-facing AI endpoint. Returns a text/event-stream SSE response. On each request: checks Redis sliding-window rate limit (10 req/min per entity_id) → 
  builds device context → retrieves RAG documents → constructs system prompt → streams LLM tokens to the client. After streaming completes: parses for work order JSON → creates work
  order in PostgreSQL if found → indexes the Q&A pair back to ChromaDB → writes AuditLog entry. Each SSE event is a typed JSON object: {type: "token"|"work_order"|"done"|"error",     
  content/data}.                                            

  knowledge_base/seed.py

  CLI tool for populating ChromaDB. Accepts --dir (directory of PDFs/text files), --file (single file), --device-class, --type (manual/fault_resolution/policy). Uses pypdf for PDF    
  extraction and LangChain's RecursiveCharacterTextSplitter (1000-char chunks, 200-char overlap). Calls ChromaDB upsert() with stable IDs so re-seeding is idempotent.
                                                                                                                                                                                       
  knowledge_base/fault_history_sample.csv                                                                                                                                              
  
  6 sample fault resolution records (2 HVAC, 1 energy, 2 network, 1 infra) with question/answer pairs seeded into ChromaDB. Bootstraps the RAG pipeline before real fault history      
  accumulates.                                              
                                                                                                                                                                                       
  ---                                                       
  Phase 4 — Custom Widgets (Days 10–11)
                                                                                                                                                                                       
  widgets/vantage_chat.html
                                                                                                                                                                                       
  Vanilla HTML/JS widget for the ThingsBoard dashboard. On init, reads entity_id and FASTAPI_URL from the widget context. Displays a live telemetry strip (up to 6 pills showing       
  current values). Chat input supports Ctrl+Enter shortcut and auto-resizes. Messages stream via fetch() + ReadableStream (not EventSource, which doesn't support POST). Shows a 3-dot
  typing animation during the streaming phase. Renders LLM tokens with basic markdown (bold, italic, inline code, bullet points). When the stream contains a work_order event, renders 
  a structured work order card. A copy button appears on completion. All state is reset cleanly on widget destroy.

  widgets/vantage_workorders.html

  Vanilla HTML/JS widget showing the maintenance queue for the current device. Fetches GET /workorders?entity_id=…&status=open,acknowledged,in_progress and renders priority cards     
  (P1–P5 with colour coding). Each card shows fault description, due date, labour hours, and a status dropdown. Submitting a status change calls PATCH /workorders/{id}/status. Overdue
   work orders (due_by in the past) highlight the date in red with a left red border. Auto-refreshes every 60 seconds via setInterval(), cleared on widget destroy.                    
                                                            
  widgets/WIDGET_REGISTRATION.md                                                                                                                                                       
  
  Step-by-step instructions for registering both widgets in the ThingsBoard widget library: create widget bundle, paste HTML, configure the settings schema JSON (which exposes        
  FASTAPI_URL as a user-configurable field), and verification checklist.
                                                                                                                                                                                       
  ---                                                       
  Phase 5 — Anomaly Detection (Days 12–14)

  fastapi/services/anomaly.py

  Full Isolation Forest anomaly detection service with one model per device class (hvac/energy/network/infra). Each model is trained on a list[dict] of telemetry readings. Scoring    
  maps the raw IF score to a 0–100 scale and computes per-feature sigma (standard deviations from baseline mean). The plain-English explanation identifies the most anomalous feature:
  "Power Consumption is 3.8σ above 30-day baseline (23% higher than normal)." Models persist via joblib; loaded into an in-memory cache on first use. get_anomaly_service() singleton. 
                                                            
  fastapi/consumers/telemetry.py

  Full Kafka consumer replacing the stub. Uses AIOKafkaConsumer with manual commit (enable_auto_commit=False) and AIOKafkaProducer for the dead-letter queue (platform2.dlq). For each 
  message: deserialises JSON → scores with Isolation Forest (via run_in_executor to avoid blocking the event loop) → writes AnomalyScore row to TimescaleDB → if anomaly:
  creates/enriches a ThingsBoard alarm with severity mapped from score (≥80=CRITICAL, ≥60=MAJOR, ≥40=WARNING) → uses Redis to dedup alarms already enriched by the webhook path. Failed
   messages (parse errors, scoring errors) go to the DLQ with a failure reason header; the consumer continues processing.

  scripts/train_anomaly.py                                                                                                                                                             
  
  Training script for production use. Connects to ThingsBoard via sync HTTP client, pages all tenant devices, filters by device_class, fetches up to 10,000 historical telemetry       
  readings per device (last 30 days), and trains the Isolation Forest for each class. Validates the trained model against a known anomaly sample before saving.
                                                                                                                                                                                       
  scripts/generate_synthetic_baseline.py                                                                                                                                               
   
  Pre-seeding script for day-1 use before real data exists. Generates 30 days of synthetic telemetry at 5-minute intervals for all device classes using time-of-day sinusoidal patterns
   and business-hours modifiers. Injects 3 realistic anomalies per class at random timestamps. Trains Isolation Forest models from the synthetic data, validates detection against a
  fresh anomaly sample and a normal sample, and optionally publishes historical telemetry to ThingsBoard via the REST batch ingestion API (with explicit timestamps).                  
                                                            
  ---
  Phase 6 — Predictive Maintenance (Days 15–16)
                                                                                                                                                                                       
  fastapi/services/predictive.py
                                                                                                                                                                                       
  LSTM predictive maintenance service. The FailureLSTM PyTorch model is a 2-layer LSTM (input→64→32) followed by Dropout(0.2) and Linear(32→1)→Sigmoid. It takes a 24-step sequence of 
  hourly telemetry and outputs a failure probability.
                                                                                                                                                                                       
  train() — fits a MinMaxScaler on the training data, builds overlapping windows, and trains with BCELoss. Addresses class imbalance with BCEWithLogitsLoss(pos_weight=n_neg/n_pos).   
  Saves the model state dict (.pth) and scaler + feature names (.pkl) separately.
                                                                                                                                                                                       
  score_device() — fetches the last 26 hours of telemetry from ThingsBoard, takes the most recent 24 readings, scales them, runs inference, and maps probability to a failure window:  
  ≥0.90 → "24hr", ≥0.80 → "48hr", else "72hr".
                                                                                                                                                                                       
  generate_work_order_data() — uses WO_TEMPLATES (per-class: parts list with stock codes, safety prerequisites, skill level, labour hours) to generate a structured work order when    
  failure is predicted.
                                                                                                                                                                                       
  _feature_attribution() — computes per-feature standard deviation across the sequence as a proxy for contribution; normalised to sum to 1.                                            
   
  fastapi/services/predictive_batch.py                                                                                                                                                 
                                                            
  Daily batch job scheduled by APScheduler. Pages all ThingsBoard devices, filters to BMS device classes (hvac/energy/occupancy/elevator/fire), and runs LSTM scoring concurrently with
   a Semaphore(10) limit. For each device above threshold: checks Redis 48-hour dedup key to prevent duplicate alarms → creates PREDICTIVE_FAILURE alarm in ThingsBoard → writes LSTM
  scores as server attributes → creates work order in PostgreSQL with due_by set to end of the predicted failure window. Returns a summary dict (devices_scored, failures_predicted,   
  alarms_created, work_orders_created, errors).             

  scripts/train_lstm.py                                                                                                                                                                
   
  Synthetic training data generator + trainer for LSTM models. gen_normal_sequence() generates healthy operating data with time-of-day patterns. gen_failure_sequence() applies        
  exponential degradation (severity = 0.1 + 0.9 × progress²) so faults accelerate toward the end of the sequence — realistic for bearing wear, PF degradation, resource exhaustion, and
   link failures. Labels the last 8 steps of each failure sequence as positive. After training, validates on fresh failure and normal sequences loaded from disk (tests the full       
  save/load/inference path).                                

  ---
  Phase 7 — GNN Root Cause Analysis (Day 17)
                                            
  fastapi/services/topology.py
                                                                                                                                                                                       
  Builds and maintains a NetworkX DiGraph representing all device relationships. async_build() pages all ThingsBoard devices, fetches their relation lists in both directions (FROM and
   TO), and maps ThingsBoard relation types to 5 typed edges: contains, handover, power_dependency, network_adjacency, hvac_zone. Also infers implicit edges from device_class         
  co-location (e.g. energy→hvac on the same floor = power_dependency). Persists as gpickle. get_subgraph(entity_ids, hops=2) returns the neighbourhood of any set of devices for GNN   
  input. stats() returns node/edge counts by type. Module-level singleton via get_topology().

  fastapi/services/gnn.py

  Graph Convolutional Network root cause analysis. _GCNModel is a 2-layer GCN (GCNConv(5→32)→ReLU→Dropout(0.3)→GCNConv(32→16)→Linear(16→1)→Sigmoid) with a plain-Linear fallback when  
  PyTorch Geometric is not installed.
                                                                                                                                                                                       
  Node features (5-dim): device_class_idx/6, normalised alarm count, normalised anomaly score, is_in_cascade flag, cascade position.                                                   
   
  find_root_cause() — if a trained model exists, builds the topology subgraph, constructs the feature matrix and edge index, runs GCN inference, and picks the cascade node with the   
  highest output probability. Falls back to a topology-aware heuristic (highest in-degree in the cascade subgraph; anomaly score and cascade position break ties).
                                                                                                                                                                                       
  train_from_audit_log() — reads alarm_cascade_analyzed AuditLog entries (written by the webhook cascade handler), trains the GCN on confirmed cascade histories, and saves            
  gnn_rootcause.pth.
                                                                                                                                                                                       
  ---                                                       
  Phase 8 — Demo Simulator + Load Test (Days 18–19)
                                                   
  simulator/devices.json
                                                                                                                                                                                       
  Registry of 16 virtual demo devices: 4 HVAC (AHU-01–03, FCU-01), 3 energy (MSB-01, DB-FLOOR1/2), 4 network (SW-CORE-01, SW-ACCESS-01/02, FW-01), 3 infra (SRV-APP-01, SRV-DB-01,     
  SRV-BACKUP-01), 2 occupancy (OCC-LOBBY, OCC-FLOOR1). Each has floor, zone, label, device_class, and MQTT access token.                                                               
                                                                                                                                                                                       
  simulator/mqtt_sim.py                                     

  MQTT telemetry simulator. Creates one DevicePublisher (paho-mqtt client) per device, authenticated with its access token. Runs an independent async loop per device that generates   
  realistic telemetry using time-of-day sinusoidal patterns and business-hours modifiers (per device class). On each cycle, checks the _INJECTIONS shared dict and merges any active
  fault overrides into the payload before publishing. Handles SIGINT/SIGTERM cleanly. Startup is staggered with random delays to avoid a thundering herd at boot.                      
                                                            
  simulator/fault_injector.py

  FastAPI server on port 8001. Loads scenario JSON files from scenarios/, applies telemetry overrides for the specified devices, and persists the injection state to a JSON file       
  (/tmp/vantage_injections.json) that the simulator reads on every publish cycle.
  - POST /inject/{scenario} — activates a scenario for its configured duration                                                                                                         
  - GET /scenarios — lists all available scenarios with descriptions                                                                                                                   
  - GET /status — shows active injections with human-readable expiry times
  - POST /reset / POST /reset/{device_name} — clears injections                                                                                                                        
                                                                                                                                                                                       
  simulator/scenarios/hvac_bearing_wear.json                                                                                                                                           
                                                                                                                                                                                       
  3-step HVAC bearing wear scenario (10 minutes) on AHU-01. Step 1: subtle vibration rise. Step 2: moderate wear (anomaly score climbs past threshold). Step 3: severe degradation     
  (PREDICTIVE_FAILURE triggered). Includes a 7-step demo script for the presenter.
                                                                                                                                                                                       
  simulator/scenarios/nms_cascade.json                                                                                                                                                 
   
  3-step network cascade scenario (8 minutes). SW-CORE-01 develops a port fault (root cause), which cascades to SW-ACCESS-01, SW-ACCESS-02, and finally SRV-APP-01. Tests the GNN      
  cascade detection path end-to-end. Demo script included.  
                                                                                                                                                                                       
  simulator/scenarios/motor_prefailure.json                                                                                                                                            
   
  3-step power factor degradation scenario (9 minutes) on MSB-01 and DB-FLOOR1. PF degrades from 0.92 → 0.71 → 0.60, crossing the utility penalty threshold. Triggers LOW_POWER_FACTOR 
  alarm and auto-creates a capacitor bank replacement work order. Demo script included.
                                                                                                                                                                                       
  simulator/Dockerfile + simulator/requirements.txt                                                                                                                                    
   
  Python 3.11-slim image that installs paho-mqtt, FastAPI, Uvicorn, httpx, Pydantic. Default CMD runs both the fault injector and the MQTT simulator in the same container (demo       
  profile only).                                            
                                                                                                                                                                                       
  tests/locustfile.py                                       

  Locust load test with two user classes:                                                                                                                                              
  - OperatorUser (2–8s think time) — weighted mix of: chat SSE requests (consuming full stream, reporting time-to-first-token as a separate metric), work order list/get, alarm
  webhook, cascade webhook, health probes                                                                                                                                              
  - AlarmStormUser (0.1–0.5s think time) — alarm-only burst traffic to simulate a power event
                                                                                                                                                                                       
  Custom @events.quitting listener prints a summary table with request counts, failure counts, p50, and p95 for each key endpoint.                                                     
                                                                                                                                                                                       
  ---                                                                                                                                                                                  
  Phase 9 — Production Packaging (Day 20)                                                                                                                                              
                                                                                                                                                                                       
  Makefile
                                                                                                                                                                                       
  25 self-documenting make targets grouped by function. make help lists all with descriptions. Key targets:                                                                            
  - Stack: start, stop, restart, status, logs, logs-fastapi, build, build-no-cache
  - Demo: demo (starts with simulator + prints URLs + scenario list), demo-stop, inject SCENARIO=…, reset-injections                                                                   
  - Setup: onboard, migrate                                                                                         
  - Knowledge: seed-knowledge, seed-faults                                                                                                                                             
  - Training: train-anomaly, train-lstm, build-topology, train-gnn, train-all, generate-baseline                                                                                       
  - Backup: backup, backup-pg, backup-chroma, restore-pg BACKUP_FILE=…                                                                                                                 
  - Testing: load-test (headless, 50 users, 120s), load-test-ui                                                                                                                        
  - Dev: shell, shell-db, run-predictive                                                                                                                                               
  - Cleanup: clean, clean-models, clean-all (destructive, requires typing "yes")                                                                                                       
  - check-env runs before start to warn about missing .env or required secrets                                                                                                         
                                                                                                                                                                                       
  docker-compose.prod.yml                                                                                                                                                              
                                                                                                                                                                                       
  Production overlay applied on top of docker-compose.yml. Changes:                                                                                                                    
  - All service ports restricted to 127.0.0.1 (reverse proxy termination in front)
  - Kafka, PostgreSQL, Redis external ports removed entirely (internal traffic only)                                                                                                   
  - CPU and memory limits on every service (ThingsBoard: 2GB, FastAPI: 2GB, Kafka: 1GB, PostgreSQL: 1GB)
  - PostgreSQL tuned with shared_buffers, work_mem, checkpoint_completion_target, slow query logging                                                                                   
  - FastAPI runs with 4 Uvicorn workers (--workers 4) with uvloop                                                                                                                      
  - FastAPI source directory mounted read-only; only models/ remains writable                                                                                                          
  - JSON file log driver on all services with size rotation (50MB × 10 for FastAPI)                                                                                                    
                                                                                                                                                                                       
  CUSTOMER_ONBOARDING.md                                                                                                                                                               
                                                                                                                                                                                       
  10-section operator runbook, entirely free of any internal implementation references:                                                                                                
                                                                                                                                                                                       
  1. Prerequisites — hardware/OS/Docker requirements table, open port list                                                                                                             
  2. First-time installation — clone, .env configuration, make start, verification
  3. Device onboarding — CSV format, make onboard, MQTT credentials, telemetry key reference table per device class                                                                    
  4. Dashboard setup — rule chain import, widget registration, FASTAPI_URL configuration                                                                                               
  5. AI model training — live data path vs synthetic baseline, individual model targets, timing estimates                                                                              
  6. Knowledge base — adding PDFs/text, make seed-knowledge, make seed-faults                                                                                                          
  7. Day-2 operations — health check, log tailing, backup commands, cron example, retraining cadence                                                                                   
  8. Vantage Chat guide — example questions, what the AI does with each, tips                                                                                                          
  9. Vantage WorkOrders guide — lifecycle states, priority colour table, overdue handling                                                                                              
  10. Troubleshooting — 5 common failure modes with diagnostic commands, demo mode walkthrough with make inject SCENARIO=…   