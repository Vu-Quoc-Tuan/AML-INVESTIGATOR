FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY app ./app
COPY config ./config
# Warm-start path used by the shared data repository (optional at runtime).
COPY data/generated ./data/generated

RUN chown -R app:app /app
USER app

EXPOSE 8000

# Public edge: Cloudflare Tunnel → 127.0.0.1:8000 on the host.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
