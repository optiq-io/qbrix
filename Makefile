.PHONY: help proto install test lint fmt clean \
        infra infra-down \
        dev dev-proxy dev-motor dev-cortex \
        docker docker-build docker-build-no-cache docker-up docker-down docker-logs docker-ps \
        db-reset

help:
	@echo "Qbrix Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install              Install all dependencies"
	@echo "  make proto                Generate protobuf stubs"
	@echo ""
	@echo "Development:"
	@echo "  make infra                Start infrastructure (postgres + redis)"
	@echo "  make infra-down           Stop infrastructure"
	@echo "  make dev                  Start all services locally (requires infra)"
	@echo "  make dev-proxy            Start proxy service only"
	@echo "  make dev-motor            Start motor service only"
	@echo "  make dev-cortex           Start cortex service only"
	@echo ""
	@echo "Docker:"
	@echo "  make docker               Build and start all containers"
	@echo "  make docker-build         Build all containers"
	@echo "  make docker-build-no-cache  Build all containers without cache"
	@echo "  make docker-up            Start all containers"
	@echo "  make docker-down          Stop all containers"
	@echo "  make docker-logs          Tail logs from all containers"
	@echo "  make docker-ps            Show running containers"
	@echo ""
	@echo "Testing & Quality:"
	@echo "  make test                 Run all tests"
	@echo "  make lint                 Run linters"
	@echo "  make fmt                  Format code"
	@echo ""
	@echo "Utilities:"
	@echo "  make db-reset             Reset postgres database"
	@echo "  make clean                Clean generated files and caches"

# ============================================================================
# Setup
# ============================================================================

install:
	uv sync

proto:
	./bin/generate-proto.sh

# ============================================================================
# Development (local services with docker infra)
# ============================================================================

infra:
	docker compose up -d postgres redis
	@echo "Waiting for services to be healthy..."
	@sleep 3
	@docker compose ps

infra-down:
	docker compose down postgres redis

dev: infra
	@echo "Starting all services..."
	@trap 'kill 0' EXIT; \
	PROXY_POSTGRES_HOST=localhost PROXY_REDIS_HOST=localhost PROXY_MOTOR_HOST=localhost \
	uv run python -m proxysvc & \
	MOTOR_REDIS_HOST=localhost \
	uv run python -m motorsvc & \
	CORTEX_REDIS_HOST=localhost \
	uv run python -m cortexsvc & \
	wait

dev-proxy:
	PROXY_POSTGRES_HOST=localhost PROXY_REDIS_HOST=localhost PROXY_MOTOR_HOST=localhost \
	uv run python -m proxysvc

dev-motor:
	MOTOR_REDIS_HOST=localhost \
	uv run python -m motorsvc

dev-cortex:
	CORTEX_REDIS_HOST=localhost \
	uv run python -m cortexsvc

# ============================================================================
# Docker Compose (full containerized setup)
# ============================================================================

docker: docker-build docker-up

docker-build:
	docker compose build

docker-build-no-cache:
	docker compose build --no-cache

docker-up:
	docker compose up -d
	@docker compose ps

# ============================================================================
# Testing & Quality
# ============================================================================

test:
	uv run pytest

lint:
	uv run black --check .
	uv run mypy .

fmt:
	uv run black .

# ============================================================================
# Utilities
# ============================================================================

db-reset:
	docker compose down postgres
	docker volume rm qbrix_postgres_data 2>/dev/null || true
	docker compose up -d postgres
	@echo "Waiting for postgres to be ready..."
	@sleep 3

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ dist/ build/