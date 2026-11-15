# Everyday commands. Each one says what it runs, so it doubles as
# documentation; CLAUDE.md and the README have the detail behind them.

BACKEND := backend
FRONTEND := frontend
VENV := $(BACKEND)/venv/bin
REGISTRY ?= ghcr.io/marco308

.PHONY: help run migrate test lint format frontend-dev frontend-check ios-test deploy

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

run: migrate ## Backend on https://127.0.0.1:8000 with reload (needs backend/certs, see CLAUDE.md)
	cd $(BACKEND) && venv/bin/uvicorn app.main:app --reload \
		--ssl-keyfile=./certs/localhost+2-key.pem --ssl-certfile=./certs/localhost+2.pem

migrate: ## Apply Alembic migrations to the local database
	cd $(BACKEND) && venv/bin/alembic upgrade head

test: ## Backend test suite
	cd $(BACKEND) && venv/bin/pytest tests

lint: ## Ruff lint and format check, as CI runs them
	cd $(BACKEND) && venv/bin/ruff check app scripts tests && venv/bin/ruff format --check app scripts tests

format: ## Apply ruff fixes and formatting
	cd $(BACKEND) && venv/bin/ruff check --fix app scripts tests && venv/bin/ruff format app scripts tests

frontend-dev: ## Vite dev server
	cd $(FRONTEND) && npm run dev

frontend-check: ## Frontend lint, format check and type-checked build, as CI runs them
	cd $(FRONTEND) && npm run lint && npm run format:check && npm run build

ios-test: ## iOS unit tests on a simulator (set IOS_DEST to pick one)
	cd ios/PodcastManager && xcodegen generate && xcodebuild test \
		-project PodcastManager.xcodeproj -scheme PodcastManager \
		-destination '$(or $(IOS_DEST),platform=iOS Simulator,name=iPhone 17)'

deploy: ## Deploy the checked-out commit's published images (run on the swarm manager)
	REGISTRY=$(REGISTRY) ./deploy.sh all
