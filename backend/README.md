# AML Investigator backend

The investigation workflow loads its OpenAI-compatible model configuration from
the ignored `backend/.env` file:

```dotenv
API_KEY=
BASE_URL=
MODEL_NAME=glm-5.2-free
```

Never place a real credential in `.env.example` or commit `.env`.

From `backend/`, run the network-free suite by default:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run real-endpoint tests explicitly only when `backend/.env` is configured. Run
the three groups separately so a low-quota endpoint can reset its rate-limit
window between groups:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts= -m live_llm tests/integration/test_llm_capabilities.py
.\.venv\Scripts\python.exe -m pytest -o addopts= -m live_llm tests/integration/test_live_llm_agents.py
.\.venv\Scripts\python.exe -m pytest -o addopts= -m live_llm tests/integration/test_live_llm_workflow.py
```

If the provider returns `RateLimitError`, wait for its quota window to reset
before starting the next group. Do not treat a rate-limited combined run as a
contract failure when all three groups pass independently.

The default checkpointer is in-memory and intended for development. The compiled
workflow accepts an injected checkpointer when durable persistence is added later.
