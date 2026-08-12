.PHONY: help install dev test test-backend test-frontend lint lint-backend lint-frontend build clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install backend + frontend dependencies
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install

dev: ## Run backend (:8000) and frontend (:5173) in dev mode
	.venv/bin/uvicorn app.main:app --reload --port 8000 & \
	cd frontend && npm run dev

test: test-backend test-frontend ## Run all tests

test-backend: ## Run backend tests
	.venv/bin/pytest tests/ -q

test-frontend: ## Run frontend unit tests
	cd frontend && npm test -- --run

lint: lint-backend lint-frontend ## Run all linters

lint-backend: ## Lint Python with ruff
	ruff check app/ tests/

lint-frontend: ## Lint frontend with eslint
	cd frontend && npm run lint

build: ## Build frontend production bundle
	cd frontend && npm run build

clean: ## Remove build artifacts and caches
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name .pytest_cache -type d -prune -exec rm -rf {} +
	rm -rf frontend/dist
