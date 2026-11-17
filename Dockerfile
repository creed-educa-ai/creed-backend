# Imagem do backend — deploy na EC2.
FROM python:3.12-slim AS base

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
# O primeiro admin de produção nasce por `python -m scripts.convidar_primeiro_admin`,
# rodado nesta imagem (P-052). Só esse script entra: o seed_local.py cria admin com
# senha conhecida, e a barreira dele (ENVIRONMENT=local) não segura quem roda a
# imagem sem ENVIRONMENT, porque o padrão do config.py é "local". Script novo de
# scripts/ entra aqui pelo nome, e só se puder rodar em produção.
COPY scripts/__init__.py scripts/convidar_primeiro_admin.py ./scripts/

# Usuário não-root
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Migrations NÃO rodam aqui (princípio #2): o deploy.sh do creed-infrastructure as
# roda num container descartável desta imagem antes de recriar o back.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
