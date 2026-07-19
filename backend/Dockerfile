FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY app ./app
COPY config ./config
COPY data ./data
COPY model ./model

# Writable path for SQLite detection/ticket/control DB (mounted volume preferred).
RUN mkdir -p /app/runtime && chown -R app:app /app

USER app

ENV DETECTION_DB_PATH=/app/runtime/detection_queue.db \
    DETECTION_MODEL_PATH=/app/model/xgb_model.json \
    DETECTION_ENRICHMENT_DATA_PATH=/app/data/generated

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
