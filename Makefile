PYTHON ?= $(if $(wildcard backend/.venv/bin/python),backend/.venv/bin/python,python3)
BACKEND_IMAGE ?= aml-investigator-backend:local
COMPOSE_PROJECT_NAME ?= aml-investigator

.PHONY: lint ci frontend-lint frontend-build backend-docker-build docker-config docker-up-backend docker-down

lint: frontend-lint

frontend-lint:
	cd frontend && npm run lint

frontend-build:
	cd frontend && npm run build

backend-docker-build:
	docker build --file backend/Dockerfile --tag $(BACKEND_IMAGE) backend

docker-config:
	docker compose -f docker-compose.yml config --quiet

docker-up-backend:
	docker compose -p $(COMPOSE_PROJECT_NAME) up --detach --build backend

docker-down:
	docker compose -p $(COMPOSE_PROJECT_NAME) down

ci: frontend-lint frontend-build docker-config
