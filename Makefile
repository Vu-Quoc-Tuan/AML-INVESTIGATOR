PYTHON ?= $(if $(wildcard backend/.venv/bin/python),backend/.venv/bin/python,python3)
FRONTEND_IMAGE ?= aml-investigator-frontend:local
COMPOSE_PROJECT_NAME ?= aml-investigator

.PHONY: lint test ci frontend-lint frontend-build frontend-docker-build docker-config docker-up-frontend docker-down

lint: frontend-lint

test:
	@echo "No automated test suite wired yet"

frontend-lint:
	cd frontend && npm run lint

frontend-build:
	cd frontend && npm run build

frontend-docker-build:
	docker build --file frontend/Dockerfile --tag $(FRONTEND_IMAGE) frontend

docker-config:
	docker compose -f docker-compose.yml config --quiet

docker-up-frontend:
	docker compose -p $(COMPOSE_PROJECT_NAME) up --detach --build frontend

docker-down:
	docker compose -p $(COMPOSE_PROJECT_NAME) down

ci: frontend-lint frontend-build docker-config frontend-docker-build
