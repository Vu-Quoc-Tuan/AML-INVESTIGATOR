FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY app ./app
COPY config ./config
COPY data/generated ./data/generated

RUN chown -R app:app /app
USER app

# The current backend is a data-layer scaffold. Replace this command with
# uvicorn app.main:app once the FastAPI application object is implemented.
CMD ["python", "-c", "from app.main import initialize_backend; initialize_backend(); print('Backend scaffold initialized')"]
