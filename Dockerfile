FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/api/src \
    PORT=8080

WORKDIR /app

RUN useradd --create-home --uid 10001 forgegraph

COPY pyproject.toml README.md /app/
COPY apps/api /app/apps/api
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY reference-pack /app/reference-pack

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && rm -rf /root/.cache

USER forgegraph
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live')"

CMD ["uvicorn", "forgegraph.main:app", "--host", "0.0.0.0", "--port", "8080"]
