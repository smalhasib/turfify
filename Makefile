.PHONY: help up down logs ps reset \
        backend-install backend-dev backend-test backend-lint \
        frontend-install frontend-dev frontend-test frontend-e2e frontend-lint \
        test

help:
	@echo "Turfify — Development commands"
	@echo ""
	@echo "Infrastructure:"
	@echo "  make up                 Start docker-compose dev stack"
	@echo "  make down               Stop docker-compose"
	@echo "  make logs               Tail logs"
	@echo "  make ps                 Show container status"
	@echo "  make reset              Wipe volumes + restart"
	@echo ""
	@echo "Backend:"
	@echo "  make backend-install    Install Python deps"
	@echo "  make backend-dev        Run uvicorn with reload"
	@echo "  make backend-test       Run unit + integration tests"
	@echo "  make backend-lint       Ruff + mypy"
	@echo ""
	@echo "Frontend:"
	@echo "  make frontend-install   pnpm install"
	@echo "  make frontend-dev       pnpm dev"
	@echo "  make frontend-test      Vitest"
	@echo "  make frontend-e2e       Playwright"
	@echo "  make frontend-lint      ESLint + tsc"
	@echo ""
	@echo "  make test               Run ALL tests (unit + integration + e2e)"

# --- Infrastructure ---
up:
	docker compose -f docker-compose.dev.yml up -d

down:
	docker compose -f docker-compose.dev.yml down

logs:
	docker compose -f docker-compose.dev.yml logs -f

ps:
	docker compose -f docker-compose.dev.yml ps

reset:
	docker compose -f docker-compose.dev.yml down -v
	docker compose -f docker-compose.dev.yml up -d

# --- Backend ---
backend-install:
	cd backend && pip install -e ".[dev]"

backend-dev:
	cd backend && uvicorn app.main:app --reload --port 8800

backend-test:
	cd backend && pytest tests/unit tests/integration -x

backend-test-unit:
	cd backend && pytest tests/unit -x

backend-test-integration:
	cd backend && pytest tests/integration -x

backend-lint:
	cd backend && ruff check . && ruff format --check . && mypy app

# --- Frontend ---
frontend-install:
	cd frontend && pnpm install

frontend-dev:
	cd frontend && pnpm dev

frontend-test:
	cd frontend && pnpm test

frontend-e2e:
	cd frontend && pnpm test:e2e

frontend-lint:
	cd frontend && pnpm lint && pnpm type-check

# --- Everything ---
test: backend-test frontend-test frontend-e2e
