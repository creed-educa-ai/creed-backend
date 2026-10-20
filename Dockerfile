# Imagem do backend — deploy na EC2.
FROM python:3.12-slim AS base

LABEL org.opencontainers.image.source=https://github.com/creed-educa-ai/creed-backend

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Usuário não-root
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# NOTA: migrations NÃO rodam aqui (ADR-002, secao 2.4.d) — Job dedicado no Helm.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
