UV ?= uv
PROVIDER ?= mock
.PHONY: sync sync-watch setup up down seed test lint eval demo demo-docker demo-local demo-reset

setup:            ## install dependencies
	$(UV) sync

up:               ## start postgres + api + dashboard with Docker (n8n: COMPOSE_PROFILES=n8n make up)
	docker compose up -d --build --wait

down:
	docker compose down

seed:             ## migrate and load reference data (needs DATABASE_URL, default localhost:5432)
	$(UV) run python -m opspilot.db.seed

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy

eval:             ## evaluation report in reports/ (PROVIDER=openai for the real model)
	$(UV) run python -m opspilot.eval.run --provider $(PROVIDER)
	$(UV) run python -m opspilot.eval.run --provider $(PROVIDER) --dataset personal

sync:             ## fetch new mail from your mailbox once (read-only IMAP; set IMAP_* in .env)
	$(UV) run python -m opspilot.sync.imap_sync

sync-watch:       ## keep syncing every SYNC_INTERVAL_SECONDS
	$(UV) run python -m opspilot.sync.imap_sync --watch

demo:             ## one command, no API key: Docker if available, otherwise embedded Postgres
	@if command -v docker >/dev/null 2>&1; then $(MAKE) demo-docker; else $(MAKE) demo-local; fi

demo-docker:      ## dashboard on :8501, API on :8000
	docker compose up -d --build --wait
	@echo "Dashboard: http://localhost:8501   API docs: http://localhost:8000/docs"

demo-local: setup ## no Docker needed: embedded Postgres + API + dashboard
	$(UV) run python -m opspilot.demo

demo-reset:       ## forget the embedded demo database
	rm -rf $$HOME/.opspilot-demo
