PYTHON ?= $(if $(wildcard backend/.venv/bin/python),backend/.venv/bin/python,python3)
BACKEND_PYTHON = PYTHONPATH=backend $(PYTHON)

COMPOSE ?= docker compose
COMPOSE_FILE ?= docker-compose.yml
COMPOSE_CMD = $(COMPOSE) -f $(COMPOSE_FILE)

# Local Docker defaults (browser → host-mapped backend on loopback :8000).
# Production: FE on Vercel, BE via Cloudflare Tunnel (see README Deploy).
export NEXT_PUBLIC_API_BASE_URL ?= http://localhost:8000/api/v1
export CORS_ORIGINS ?= http://localhost:3000

.PHONY: backend-lint backend-compile backend-test \
	up up-backend down build logs ps restart rebuild status shell-backend shell-frontend

backend-lint:
	$(BACKEND_PYTHON) -m ruff check --select E9,F63,F7,F82 backend/app backend/scripts backend/tests
	$(BACKEND_PYTHON) -m ruff check backend/app/main.py backend/scripts/run_mock_investigation.py backend/tests/unit/test_main.py backend/tests/unit/test_model.py

backend-compile:
	$(BACKEND_PYTHON) -m compileall -q backend/app backend/scripts backend/tests
	$(BACKEND_PYTHON) -c "from fastapi import FastAPI; from app.main import app; assert isinstance(app, FastAPI)"

backend-test:
	$(BACKEND_PYTHON) -m pytest -p no:cacheprovider backend/tests -m "not live_llm"

## Docker
## Local full stack:  make up          → FE :3000 + BE 127.0.0.1:8000
## BE only (CD-like): make up-backend  → same contract as GitHub CD
## Production FE is Vercel, not the compose frontend service.

# Build images and start FE + BE detached.
up:
	$(COMPOSE_CMD) up -d --build

# Backend only (matches CD: compose up backend on loopback :8000).
up-backend:
	$(COMPOSE_CMD) up -d --build backend

# Stop and remove containers (keeps named volume with SQLite).
down:
	$(COMPOSE_CMD) down

# Rebuild images without starting.
build:
	$(COMPOSE_CMD) build

# Force recreate after code changes.
rebuild:
	$(COMPOSE_CMD) up -d --build --force-recreate

restart:
	$(COMPOSE_CMD) restart

logs:
	$(COMPOSE_CMD) logs -f

ps status:
	$(COMPOSE_CMD) ps

shell-backend:
	$(COMPOSE_CMD) exec backend sh

shell-frontend:
	$(COMPOSE_CMD) exec frontend sh

# Remove containers + volume (wipes detection_queue.db in Docker).
down-clean:
	$(COMPOSE_CMD) down -v
