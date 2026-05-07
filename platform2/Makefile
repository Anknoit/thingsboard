# Vantage NMS — Operational Makefile
# Usage: make <target>
# Run `make help` to list all available targets.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Config ────────────────────────────────────────────────────────────────────

COMPOSE         := docker compose
COMPOSE_DEMO    := docker compose --profile demo
COMPOSE_PROD    := docker compose -f docker-compose.yml -f docker-compose.prod.yml
FASTAPI_SVC     := fastapi
SIMULATOR_SVC   := simulator

# Backup settings
BACKUP_DIR      := ./backups
BACKUP_TS       := $(shell date +%Y%m%d_%H%M%S)

# Python inside the fastapi container
PY              := $(COMPOSE) exec $(FASTAPI_SVC) python

# Colours
RESET  := \033[0m
BOLD   := \033[1m
GREEN  := \033[32m
YELLOW := \033[33m
CYAN   := \033[36m

.PHONY: help \
        start stop restart status logs logs-fastapi logs-follow \
        build build-no-cache \
        demo demo-stop \
        seed-knowledge \
        train-anomaly train-lstm build-topology train-gnn train-all \
        migrate \
        backup backup-pg backup-chroma restore-pg \
        load-test \
        onboard \
        shell shell-db \
        clean clean-models clean-all \
        check-env


# ── Help ──────────────────────────────────────────────────────────────────────

help: ## Show this help message
	@echo ""
	@echo "  $(BOLD)Vantage NMS — Operational Commands$(RESET)"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { \
		printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2 \
	}' $(MAKEFILE_LIST) | sort
	@echo ""
	@echo "  $(YELLOW)Demo workflow:$(RESET)"
	@echo "    make demo  →  inject a fault  →  open Vantage NMS  →  make demo-stop"
	@echo ""


# ── Stack lifecycle ───────────────────────────────────────────────────────────

start: check-env ## Start all core services (production mode)
	@echo "$(GREEN)Starting Vantage NMS...$(RESET)"
	$(COMPOSE) up -d
	@echo "$(GREEN)Stack is up. Run 'make status' to verify.$(RESET)"

stop: ## Stop all services (data volumes preserved)
	@echo "$(YELLOW)Stopping Vantage NMS...$(RESET)"
	$(COMPOSE) down
	@echo "$(YELLOW)Stack stopped. Data volumes intact.$(RESET)"

restart: ## Restart all services
	$(COMPOSE) restart

status: ## Show running container status and health
	@echo "$(BOLD)Container status:$(RESET)"
	@$(COMPOSE) ps
	@echo ""
	@echo "$(BOLD)AI service health:$(RESET)"
	@curl -s http://localhost:8000/health 2>/dev/null | python3 -m json.tool || \
		echo "  FastAPI not reachable on localhost:8000"

logs: ## Tail logs for all services (last 50 lines)
	$(COMPOSE) logs --tail=50 -f

logs-fastapi: ## Tail FastAPI AI service logs only
	$(COMPOSE) logs --tail=100 -f $(FASTAPI_SVC)

logs-follow: ## Follow logs for a specific service (SERVICE=name)
	$(COMPOSE) logs --tail=50 -f $(SERVICE)

build: ## Build / rebuild all Docker images
	$(COMPOSE) build

build-no-cache: ## Force rebuild all images without cache
	$(COMPOSE) build --no-cache


# ── Demo mode ─────────────────────────────────────────────────────────────────

demo: check-env ## Start full stack including MQTT simulator and fault injector
	@echo "$(GREEN)Starting Vantage NMS in demo mode...$(RESET)"
	$(COMPOSE_DEMO) up -d
	@echo ""
	@echo "  $(BOLD)Fault injector:$(RESET)  http://localhost:8001/docs"
	@echo "  $(BOLD)Vantage NMS UI:$(RESET)  http://localhost:8080"
	@echo "  $(BOLD)AI services:$(RESET)     http://localhost:8000/docs"
	@echo ""
	@echo "  Available scenarios:"
	@curl -s http://localhost:8001/scenarios 2>/dev/null | \
		python3 -c "import sys,json; [print('    •', s['name'],'—', s['description'][:60]+'...') for s in json.load(sys.stdin)['scenarios']]" || \
		echo "  (fault injector starting up — wait 10s and retry)"
	@echo ""
	@echo "  $(YELLOW)Inject a fault:$(RESET)"
	@echo "    curl -X POST http://localhost:8001/inject/hvac_bearing_wear"
	@echo "    curl -X POST http://localhost:8001/inject/nms_cascade"
	@echo "    curl -X POST http://localhost:8001/inject/motor_prefailure"
	@echo ""

demo-stop: ## Stop demo mode (stops simulator, leaves core stack running)
	@echo "$(YELLOW)Stopping demo simulator...$(RESET)"
	$(COMPOSE_DEMO) stop $(SIMULATOR_SVC)
	@curl -s -X POST http://localhost:8001/reset > /dev/null 2>&1 || true
	@echo "$(YELLOW)Simulator stopped. Core stack still running.$(RESET)"

inject: ## Inject a fault scenario (SCENARIO=hvac_bearing_wear|nms_cascade|motor_prefailure)
	@if [ -z "$(SCENARIO)" ]; then \
		echo "Usage: make inject SCENARIO=hvac_bearing_wear"; \
		echo "Available: hvac_bearing_wear, nms_cascade, motor_prefailure"; \
		exit 1; \
	fi
	curl -s -X POST http://localhost:8001/inject/$(SCENARIO) | python3 -m json.tool

reset-injections: ## Clear all active fault injections
	curl -s -X POST http://localhost:8001/reset | python3 -m json.tool


# ── Device onboarding ─────────────────────────────────────────────────────────

onboard: ## Onboard all devices from scripts/devices_sample.csv into Vantage NMS
	@echo "$(GREEN)Onboarding devices...$(RESET)"
	$(COMPOSE) exec $(FASTAPI_SVC) python /app/../scripts/onboard_devices.py \
		--csv /app/../scripts/devices_sample.csv \
		--output /app/../simulator/credentials.csv
	@echo "$(GREEN)Devices onboarded. Credentials saved to simulator/credentials.csv$(RESET)"


# ── Database migrations ────────────────────────────────────────────────────────

migrate: ## Run Alembic database migrations
	@echo "$(GREEN)Running database migrations...$(RESET)"
	$(COMPOSE) exec $(FASTAPI_SVC) alembic -c /app/db/alembic.ini upgrade head
	@echo "$(GREEN)Migrations complete.$(RESET)"


# ── Knowledge base ────────────────────────────────────────────────────────────

seed-knowledge: ## Seed knowledge base from docs/ directory
	@echo "$(GREEN)Seeding knowledge base...$(RESET)"
	@if [ ! -d "./knowledge_base/docs" ] || [ -z "$$(ls -A ./knowledge_base/docs 2>/dev/null)" ]; then \
		echo "$(YELLOW)Warning: knowledge_base/docs/ is empty.$(RESET)"; \
		echo "  Add PDF or text files then re-run: make seed-knowledge"; \
	else \
		$(COMPOSE) exec $(FASTAPI_SVC) python /app/knowledge_base/seed.py \
			--dir /app/knowledge_base/docs; \
		echo "$(GREEN)Knowledge base seeded.$(RESET)"; \
	fi

seed-faults: ## Seed fault history from knowledge_base/fault_history_sample.csv
	@echo "$(GREEN)Seeding fault history...$(RESET)"
	$(COMPOSE) exec $(FASTAPI_SVC) python /app/knowledge_base/seed.py \
		--file /app/knowledge_base/fault_history_sample.csv \
		--type fault_resolution
	@echo "$(GREEN)Fault history seeded.$(RESET)"


# ── Model training ────────────────────────────────────────────────────────────

train-anomaly: ## Train Isolation Forest anomaly models (all device classes)
	@echo "$(GREEN)Training anomaly detection models...$(RESET)"
	$(COMPOSE) exec $(FASTAPI_SVC) python /app/../scripts/train_anomaly.py
	@echo "$(GREEN)Anomaly models trained and saved.$(RESET)"

train-lstm: ## Train LSTM predictive maintenance models (all device classes)
	@echo "$(GREEN)Training LSTM predictive models...$(RESET)"
	$(COMPOSE) exec $(FASTAPI_SVC) python /app/../scripts/train_lstm.py
	@echo "$(GREEN)LSTM models trained and saved.$(RESET)"

build-topology: ## Build device topology graph from live device relations
	@echo "$(GREEN)Building topology graph...$(RESET)"
	curl -s -X POST http://localhost:8000/debug/rebuild-topology | python3 -m json.tool
	@echo "$(GREEN)Topology graph saved.$(RESET)"

train-gnn: ## Train GNN root cause model from audit log cascade history
	@echo "$(GREEN)Training GNN root cause model...$(RESET)"
	curl -s -X POST "http://localhost:8000/debug/train-gnn?epochs=50" | python3 -m json.tool

train-all: ## Run full training pipeline (anomaly → LSTM → topology → GNN)
	@echo "$(BOLD)$(GREEN)Running full training pipeline...$(RESET)"
	$(MAKE) train-anomaly
	$(MAKE) train-lstm
	$(MAKE) build-topology
	$(MAKE) train-gnn
	@echo "$(BOLD)$(GREEN)All models trained.$(RESET)"

generate-baseline: ## Generate synthetic 30-day baseline and train anomaly models
	@echo "$(GREEN)Generating synthetic baseline data...$(RESET)"
	$(COMPOSE) exec $(FASTAPI_SVC) python /app/../scripts/generate_synthetic_baseline.py
	@echo "$(GREEN)Synthetic baseline generated and models trained.$(RESET)"


# ── Backup & restore ──────────────────────────────────────────────────────────

backup: backup-pg backup-chroma ## Full backup: PostgreSQL + ChromaDB
	@echo "$(GREEN)Backup complete: $(BACKUP_DIR)/$(BACKUP_TS)/$(RESET)"

backup-pg: ## Backup PostgreSQL platform2 database
	@mkdir -p $(BACKUP_DIR)/$(BACKUP_TS)
	@echo "$(GREEN)Backing up PostgreSQL...$(RESET)"
	$(COMPOSE) exec -T postgres \
		pg_dump -U p2 platform2 \
		> $(BACKUP_DIR)/$(BACKUP_TS)/platform2_pg_$(BACKUP_TS).sql
	@echo "  Saved: $(BACKUP_DIR)/$(BACKUP_TS)/platform2_pg_$(BACKUP_TS).sql"

backup-chroma: ## Backup ChromaDB vector store
	@mkdir -p $(BACKUP_DIR)/$(BACKUP_TS)
	@echo "$(GREEN)Backing up ChromaDB...$(RESET)"
	docker run --rm \
		-v platform2_chroma-data:/source:ro \
		-v $(PWD)/$(BACKUP_DIR)/$(BACKUP_TS):/backup \
		alpine tar czf /backup/chroma_$(BACKUP_TS).tar.gz -C /source .
	@echo "  Saved: $(BACKUP_DIR)/$(BACKUP_TS)/chroma_$(BACKUP_TS).tar.gz"

restore-pg: ## Restore PostgreSQL from backup (BACKUP_FILE=path/to/file.sql)
	@if [ -z "$(BACKUP_FILE)" ]; then \
		echo "Usage: make restore-pg BACKUP_FILE=backups/20260507_120000/platform2_pg_*.sql"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Restoring PostgreSQL from $(BACKUP_FILE)...$(RESET)"
	$(COMPOSE) exec -T postgres \
		psql -U p2 platform2 < $(BACKUP_FILE)
	@echo "$(GREEN)Restore complete.$(RESET)"


# ── Load testing ──────────────────────────────────────────────────────────────

load-test: ## Run Locust load test (50 users, 120 seconds)
	@command -v locust >/dev/null 2>&1 || { \
		echo "$(YELLOW)Installing locust...$(RESET)"; \
		pip install locust --quiet; \
	}
	@mkdir -p tests/results
	locust -f tests/locustfile.py \
		--host http://localhost:8000 \
		--headless \
		-u 50 -r 5 \
		--run-time 120s \
		--csv tests/results/load_$(BACKUP_TS) \
		--html tests/results/load_$(BACKUP_TS).html
	@echo "$(GREEN)Results: tests/results/load_$(BACKUP_TS).html$(RESET)"

load-test-ui: ## Run Locust with web UI (open http://localhost:8089)
	@command -v locust >/dev/null 2>&1 || pip install locust --quiet
	locust -f tests/locustfile.py --host http://localhost:8000


# ── Developer utilities ───────────────────────────────────────────────────────

shell: ## Open a bash shell in the FastAPI container
	$(COMPOSE) exec $(FASTAPI_SVC) bash

shell-db: ## Open psql in the PostgreSQL container (platform2 database)
	$(COMPOSE) exec postgres psql -U p2 platform2

run-predictive: ## Trigger predictive maintenance batch job immediately
	curl -s -X POST http://localhost:8000/debug/run-predictive | python3 -m json.tool


# ── Cleanup ───────────────────────────────────────────────────────────────────

clean: ## Remove stopped containers (data volumes preserved)
	$(COMPOSE) rm -f

clean-models: ## Delete all trained model files (re-run train-all to rebuild)
	@echo "$(YELLOW)Deleting trained model files...$(RESET)"
	rm -f models/*.pkl models/*.pth models/*.gpickle
	@echo "$(YELLOW)Models deleted. Run 'make train-all' to retrain.$(RESET)"

clean-all: ## DESTRUCTIVE: remove containers AND data volumes
	@echo "$(YELLOW)WARNING: This will delete ALL data including the database.$(RESET)"
	@read -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ] || exit 1
	$(COMPOSE) down -v
	@echo "$(YELLOW)All containers and volumes removed.$(RESET)"


# ── Environment check ─────────────────────────────────────────────────────────

check-env: ## Verify required environment variables are set
	@if [ ! -f ".env" ]; then \
		echo "$(YELLOW)Warning: .env file not found.$(RESET)"; \
		echo "  Copy .env.example to .env and fill in secrets:"; \
		echo "    cp .env.example .env && nano .env"; \
		echo ""; \
	fi
	@missing=""; \
	for var in TB_ADMIN_PASSWORD TB_DB_PASSWORD P2_DB_PASSWORD SECRET_KEY; do \
		if ! grep -q "^$$var=" .env 2>/dev/null && [ -z "$${!var}" ]; then \
			missing="$$missing $$var"; \
		fi; \
	done; \
	if [ -n "$$missing" ]; then \
		echo "$(YELLOW)Warning: Missing env vars:$$missing$(RESET)"; \
		echo "  Set these in .env before running in production."; \
		echo ""; \
	fi
