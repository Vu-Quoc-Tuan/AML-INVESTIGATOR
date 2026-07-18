PYTHON ?= $(if $(wildcard backend/.venv/bin/python),backend/.venv/bin/python,python3)
DOCKER_IMAGE ?= aml-investigator-backend:local

.PHONY: lint test ci backend-lint backend-compile backend-test docker-config docker-build

lint: backend-lint

test: backend-test

backend-lint:
	$(PYTHON) -m ruff check backend

backend-compile:
	$(PYTHON) -m compileall -q backend/app backend/tests backend/synthetic_data
	PYTHONPATH=backend $(PYTHON) -c "import app.main; print('Backend import validation passed')"

backend-test:
	$(PYTHON) -m pytest backend/tests

docker-config:
	docker compose -f docker-compose.yml config --quiet

docker-build:
	docker build --file backend/Dockerfile --tag $(DOCKER_IMAGE) backend

ci: backend-lint backend-compile backend-test docker-config docker-build
