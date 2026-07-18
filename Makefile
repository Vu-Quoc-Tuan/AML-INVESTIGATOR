PYTHON ?= $(if $(wildcard backend/.venv/bin/python),backend/.venv/bin/python,python3)
BACKEND_PYTHON = PYTHONPATH=backend $(PYTHON)

.PHONY: backend-lint backend-compile backend-test

backend-lint:
	$(BACKEND_PYTHON) -m ruff check --select E9,F63,F7,F82 backend/app backend/scripts backend/tests
	$(BACKEND_PYTHON) -m ruff check backend/app/main.py backend/scripts/run_mock_investigation.py backend/tests/unit/test_main.py backend/tests/unit/test_model.py

backend-compile:
	$(BACKEND_PYTHON) -m compileall -q backend/app backend/scripts backend/tests
	$(BACKEND_PYTHON) -c "from fastapi import FastAPI; from app.main import app; assert isinstance(app, FastAPI)"

backend-test:
	$(BACKEND_PYTHON) -m pytest -p no:cacheprovider backend/tests -m "not live_llm"
