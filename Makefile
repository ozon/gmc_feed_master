# ==============================================================================
# GMC Feed Master — Makefile
# Shortcuts for backend, frontend, infrastructure, and common dev tasks.
# All targets run from project root. Usage: make <target>
# ==============================================================================

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Paths ─────────────────────────────────────────────────────────────────────
BACKEND_DIR := backend
FRONTEND_DIR := frontend

# ── Backend env ───────────────────────────────────────────────────────────────
DATABASE_URL ?= postgresql+asyncpg://postgres:postgres@localhost:5432/gmc_feed
export DATABASE_URL

# ==============================================================================
#  Infrastructure
# ==============================================================================

.PHONY: db-up
db-up: ## Start PostgreSQL container
	docker compose up -d postgres

.PHONY: db-down
db-down: ## Stop PostgreSQL container
	docker compose down

.PHONY: db-logs
db-logs: ## Tail PostgreSQL logs
	docker compose logs -f postgres

# ==============================================================================
#  Backend
# ==============================================================================

.PHONY: backend-dev
backend-dev: ## Start FastAPI dev server (port 8000)
	cd $(BACKEND_DIR) && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --reload

.PHONY: backend-test
backend-test: ## Run backend tests (parallel)
	cd $(BACKEND_DIR) && uv run pytest -n auto

.PHONY: backend-test-seq
backend-test-seq: ## Run backend tests (sequential)
	cd $(BACKEND_DIR) && uv run pytest -n0

.PHONY: backend-lint
backend-lint: ## Lint backend with ruff
	cd $(BACKEND_DIR) && uv run ruff check .

.PHONY: backend-lint-fix
backend-lint-fix: ## Lint + auto-fix backend with ruff
	cd $(BACKEND_DIR) && uv run ruff check . --fix

.PHONY: backend-typecheck
backend-typecheck: ## Type-check backend with mypy
	cd $(BACKEND_DIR) && uv run mypy .

.PHONY: backend-migrate
backend-migrate: ## Apply database migrations (alembic upgrade head)
	cd $(BACKEND_DIR) && uv run alembic upgrade head

.PHONY: backend-migrate-down
backend-migrate-down: ## Revert database migrations (alembic downgrade base)
	cd $(BACKEND_DIR) && uv run alembic downgrade base

.PHONY: backend-migrate-new
backend-migrate-new: ## Generate new migration. Usage: make backend-migrate-new MSG="add users table"
	@test -n "$(MSG)" || (echo "ERROR: MSG is required. Usage: make backend-migrate-new MSG=\"your message\"" && exit 1)
	cd $(BACKEND_DIR) && uv run alembic revision --autogenerate -m "$(MSG)"

.PHONY: backend-check
backend-check: backend-lint backend-typecheck backend-test ## Run lint + typecheck + test

# ==============================================================================
#  Frontend
# ==============================================================================

.PHONY: frontend-install
frontend-install: ## Install frontend dependencies
	cd $(FRONTEND_DIR) && npm install

.PHONY: frontend-dev
frontend-dev: ## Start Vite dev server
	cd $(FRONTEND_DIR) && npm run dev

.PHONY: frontend-build
frontend-build: ## TypeScript check + production build
	cd $(FRONTEND_DIR) && npm run build

.PHONY: frontend-test
frontend-test: ## Run frontend tests (vitest)
	cd $(FRONTEND_DIR) && npm run test

.PHONY: frontend-typecheck
frontend-typecheck: ## Type-check frontend with tsc
	cd $(FRONTEND_DIR) && npm run typecheck

# ==============================================================================
#  Plugins
# ==============================================================================

.PHONY: plugin-test
plugin-test: ## Run plugin contract tests
	uv run pytest backend/tests/test_plugin_contract.py

# ==============================================================================
#  Registry
# ==============================================================================

.PHONY: registry-check
registry-check: ## Validate registry against gmc_def.md
	cd $(BACKEND_DIR) && uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json --check

.PHONY: registry-update
registry-update: ## Regenerate registry/attributes.json from gmc_def.md
	cd $(BACKEND_DIR) && uv run python scripts/registry_check.py --source ../gmc_def.md --output registry/attributes.json

# ==============================================================================
#  Combined workflows
# ==============================================================================

.PHONY: dev
dev: db-up ## Start all services (postgres + backend + frontend)
	@echo "Starting backend..."
	@cd $(BACKEND_DIR) && DATABASE_URL=$(DATABASE_URL) nohup uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --reload > /tmp/gmc-backend.log 2>&1 &
	@echo "Starting frontend..."
	@cd $(FRONTEND_DIR) && nohup npm run dev > /tmp/gmc-frontend.log 2>&1 &
	@echo "Backend:  http://127.0.0.1:8000"
	@echo "Frontend: http://127.0.0.1:5173"
	@echo "Logs:     /tmp/gmc-backend.log  /tmp/gmc-frontend.log"

.PHONY: dev-stop
dev-stop: ## Stop backend and frontend dev servers
	@pkill -f "uvicorn app.main:app" 2>/dev/null && echo "Backend stopped" || echo "Backend not running"
	@pkill -f "vite" 2>/dev/null && echo "Frontend stopped" || echo "Frontend not running"

.PHONY: test
test: backend-test frontend-test plugin-test ## Run all tests

.PHONY: lint
lint: backend-lint backend-typecheck frontend-typecheck ## Run all linters and type-checkers

.PHONY: check
check: lint test ## Run full CI check (lint + typecheck + all tests)

# ==============================================================================
#  Help
# ==============================================================================

.PHONY: help
help: ## Show this help
	@echo "GMC Feed Master — Available targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
