.DEFAULT_GOAL := help

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PORT := 8000

.PHONY: help install env run dev sync status docker-build docker-up docker-down docker-logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

env: ## Create the .env file from .env.example (if missing)
	@test -f .env || cp .env.example .env
	@echo "-> .env ready. Remember to edit the variables (GITLAB_*, LLM_PROVIDER, VLLM_* / ANTHROPIC_*, ...)."

install: env ## Create the virtual environment and install dependencies
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run: ## Start the server (production-like, no reload)
	$(PYTHON) -m uvicorn main:app --host 0.0.0.0 --port $(PORT)

dev: ## Start the server in development mode (auto-reload)
	$(PYTHON) -m uvicorn main:app --host 0.0.0.0 --port $(PORT) --reload

sync: ## Trigger a manual wiki synchronization
	curl -s -X POST http://localhost:$(PORT)/api/sync | python3 -m json.tool

status: ## Show the application status (indexed pages, last sync...)
	curl -s http://localhost:$(PORT)/api/status | python3 -m json.tool

docker-build: ## Build the Docker image
	docker compose build

docker-up: ## Start the application with Docker Compose
	docker compose up --build

docker-down: ## Stop the Docker Compose containers
	docker compose down

docker-logs: ## Show the container logs
	docker compose logs -f

clean: ## Remove the virtual environment and compiled Python files
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +
