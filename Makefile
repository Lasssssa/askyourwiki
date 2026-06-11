.DEFAULT_GOAL := help

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PORT := 8000

.PHONY: help install env run dev sync status docker-build docker-up docker-down docker-logs clean

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

env: ## Crée le fichier .env à partir de .env.example (si absent)
	@test -f .env || cp .env.example .env
	@echo "-> .env prêt. Pense à éditer les variables (GITLAB_*, ANTHROPIC_API_KEY / VLLM_*, ...)."

install: env ## Crée l'environnement virtuel et installe les dépendances
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run: ## Lance le serveur (production-like, sans rechargement)
	$(PYTHON) -m uvicorn main:app --host 0.0.0.0 --port $(PORT)

dev: ## Lance le serveur en mode développement (rechargement automatique)
	$(PYTHON) -m uvicorn main:app --host 0.0.0.0 --port $(PORT) --reload

sync: ## Déclenche une synchronisation manuelle des wikis
	curl -s -X POST http://localhost:$(PORT)/api/sync | python3 -m json.tool

status: ## Affiche le statut de l'application (pages indexées, dernière sync...)
	curl -s http://localhost:$(PORT)/api/status | python3 -m json.tool

docker-build: ## Construit l'image Docker
	docker compose build

docker-up: ## Lance l'application avec Docker Compose
	docker compose up --build

docker-down: ## Arrête les conteneurs Docker Compose
	docker compose down

docker-logs: ## Affiche les logs du conteneur
	docker compose logs -f

clean: ## Supprime l'environnement virtuel et les fichiers Python compilés
	rm -rf $(VENV)
	find . -type d -name "__pycache__" -exec rm -rf {} +
