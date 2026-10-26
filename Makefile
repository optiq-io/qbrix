ifneq (,$(wildcard ./.env))
    include .env
    export
endif

COMPOSE_DEV := docker compose -f docker-compose.dev.yml

.PHONY: help proto install test lint fmt clean \
        infra infra-down \
        dev dev-proxy dev-next dev-motor dev-cortex dev-trace dev-meter \
        docker docker-build docker-build-no-cache docker-up docker-down docker-logs docker-ps \
        docker-ee docker-ee-build docker-ee-build-no-cache docker-ee-up docker-ee-down docker-ee-logs \
        migrate db-reset clickhouse-reset \
        loadtest loadtest-web

help:
	@echo "Qbrix Development Commands"
	@echo ""
	@echo "Self-host quickstart (pulls published images; see .env.example):"
	@echo "  bin/selfhost-init && docker compose up -d"
	@echo ""
	@echo "Setup:"
	@echo "  make install              Install all dependencies"
	@echo "  make proto                Generate protobuf stubs"
	@echo ""
	@echo "Development:"
	@echo "  make infra                Start infrastructure (postgres + redis + clickhouse)"
	@echo "  make infra-down           Stop infrastructure"
	@echo "  make dev                  Start all services locally (requires infra)"
	@echo "  make dev-proxy            Start proxy service only"
	@echo "  make dev-next             Start proxy service with qbrix next switched on"
	@echo "  make dev-motor            Start motor service only"
	@echo "  make dev-cortex           Start cortex service only"
	@echo "  make dev-trace            Start trace service only"
	@echo "  make dev-meter            Start meter service only (EE)"
	@echo ""
	@echo "Docker (contributor stack, built from source: docker-compose.dev.yml):"
	@echo "  make docker               Build and start core containers"
	@echo "  make docker-build         Build core containers"
	@echo "  make docker-up            Start core containers"
	@echo "  make docker-down          Stop all containers"
	@echo "  make docker-logs          Tail logs from all containers"
	@echo "  make docker-ps            Show running containers"
	@echo ""
	@echo "Docker cloud edition (plus meter):"
	@echo "  make docker-ee            Build and start all containers"
	@echo "  make docker-ee-build      Build all containers"
	@echo "  make docker-ee-up         Start all containers"
	@echo "  make docker-ee-down       Stop all containers"
	@echo "  make docker-ee-logs       Tail logs from meter"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test                 Run all tests"
	@echo "  make lint                 Run linters"
	@echo "  make fmt                  Format code"
	@echo ""
	@echo "Load Testing:"
	@echo "  make loadtest             Run load test (headless, 60s, 1 auto experiment)"
	@echo "  make loadtest-web         Run load test with web UI"
	@echo ""
	@echo "Database:"
	@echo "  make migrate              Apply alembic migrations to localhost postgres"
	@echo "  make db-reset             Reset postgres database and re-apply migrations"
	@echo "  make clickhouse-reset     Reset clickhouse database"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean                Clean generated files and caches"

# ============================================================================
# Setup
# ============================================================================

install:
	uv sync --all-packages

proto:
	./bin/generate-proto.sh

# ============================================================================
# Development (local services with docker infra)
# ============================================================================

infra:
	$(COMPOSE_DEV) up -d postgres redis clickhouse
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@$(COMPOSE_DEV) ps

infra-down:
	$(COMPOSE_DEV) down postgres redis clickhouse

dev: infra migrate
	@echo "Starting all services..."
	@set -m; \
	PROXY_POSTGRES_HOST=localhost PROXY_REDIS_HOST=localhost PROXY_MOTOR_HOST=localhost PROXY_CLICKHOUSE_HOST=localhost PROXY_RUNENV=dev \
	uv run python -m proxysvc.cli serve & \
	P1=$$!; \
	MOTOR_REDIS_HOST=localhost \
	uv run python -m motorsvc.cli & \
	P2=$$!; \
	CORTEX_REDIS_HOST=localhost CORTEX_CLICKHOUSE_HOST=localhost \
	uv run python -m cortexsvc.cli & \
	P3=$$!; \
	TRACE_REDIS_HOST=localhost TRACE_CLICKHOUSE_HOST=localhost \
	uv run python -m tracesvc.cli & \
	P4=$$!; \
	trap "echo 'Shutting down...'; kill $$P1 $$P2 $$P3 $$P4; wait" INT TERM EXIT; \
	wait

dev-proxy:
	PROXY_POSTGRES_HOST=localhost PROXY_REDIS_HOST=localhost PROXY_MOTOR_HOST=localhost PROXY_CLICKHOUSE_HOST=localhost PROXY_RUNENV=dev \
	uv run python -m proxysvc.cli serve

dev-next:
	PROXY_NEXT_ENABLED=true $(MAKE) dev-proxy

dev-motor:
	MOTOR_REDIS_HOST=localhost \
	uv run python -m motorsvc.cli

dev-cortex:
	CORTEX_REDIS_HOST=localhost CORTEX_CLICKHOUSE_HOST=localhost \
	uv run python -m cortexsvc.cli

dev-trace:
	TRACE_REDIS_HOST=localhost TRACE_CLICKHOUSE_HOST=localhost \
	uv run python -m tracesvc.cli

dev-meter:
	METER_REDIS_HOST=localhost METER_POSTGRES_HOST=localhost \
	uv run python -m metersvc.cli

# ============================================================================
# Docker Compose (full containerized setup)
# ============================================================================

docker: docker-build docker-up

docker-build:
	$(COMPOSE_DEV) build

docker-build-no-cache:
	$(COMPOSE_DEV) build --no-cache

docker-up:
	$(COMPOSE_DEV) up -d
	@$(COMPOSE_DEV) ps

docker-down:
	$(COMPOSE_DEV) down

docker-logs:
	$(COMPOSE_DEV) logs -f

docker-ps:
	$(COMPOSE_DEV) ps

# ============================================================================
# Docker Compose EE (cloud edition: plus meter)
# ============================================================================

docker-ee: docker-ee-build docker-ee-up

docker-ee-build:
	QBRIX_EE_ENABLED=true $(COMPOSE_DEV) --profile cloud build

docker-ee-build-no-cache:
	QBRIX_EE_ENABLED=true $(COMPOSE_DEV) --profile cloud build --no-cache

docker-ee-up:
	QBRIX_EE_ENABLED=true $(COMPOSE_DEV) --profile cloud up -d
	@$(COMPOSE_DEV) --profile cloud ps

docker-ee-down:
	$(COMPOSE_DEV) --profile cloud down

docker-ee-logs:
	$(COMPOSE_DEV) --profile cloud logs -f meter

# ============================================================================
# Testing & Quality
# ============================================================================

lint:
	uv run black --check .

fmt:
	uv run black .

# ============================================================================
# Utilities
# ============================================================================

migrate:
	@echo "Applying database migrations..."
	POSTGRES_HOST=localhost uv run python -m qbrixstore.migrate upgrade head

db-reset:
	$(COMPOSE_DEV) down postgres
	docker volume rm qbrix-dev_qbrix_postgres_data 2>/dev/null || true
	$(COMPOSE_DEV) up -d postgres
	@echo "Waiting for postgres to be ready..."
	@until $(COMPOSE_DEV) exec -T postgres pg_isready -U qbrix >/dev/null 2>&1; do sleep 1; done
	@$(MAKE) migrate

clickhouse-reset:
	$(COMPOSE_DEV) down clickhouse
	docker volume rm qbrix-dev_qbrix_clickhouse_data 2>/dev/null || true
	$(COMPOSE_DEV) up -d clickhouse
	@echo "Waiting for clickhouse to be ready..."
	@sleep 5

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ dist/ build/

# ============================================================================
# Load Testing
# ============================================================================

loadtest:
	cd bin/ && uv run python -m loadtest.cli -u 10 -r 2 -t 60s

loadtest-web:
	cd bin/ && uv run python -m loadtest.cli --web