UV ?= uv
.PHONY: setup up down seed test lint eval demo

setup:            ## install dependencies
	$(UV) sync

up:               ## start Postgres (and API once built) via docker compose
	docker compose up -d --wait

down:
	docker compose down

seed:             ## load reference data + sample emails (added in milestone 2)
	$(UV) run python -m opspilot.db.seed

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy

PROVIDER ?= mock
eval:             ## evaluation report in reports/ (PROVIDER=openai for the real model)
	$(UV) run python -m opspilot.eval.run --provider $(PROVIDER)

demo: setup up seed  ## one command: everything running with no API key
	@echo "Demo ready (dashboard arrives in milestone 7)."
