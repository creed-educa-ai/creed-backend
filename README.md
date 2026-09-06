# CREED.ai Educa — Backend

API em FastAPI. Decisões registradas nos **ADR-001** (stack) e **ADR-002**
(organização interna e migrations).

Antes do primeiro PR, leia a [cartilha de contribuição](CONTRIBUTING.md) —
fluxo de branches, padrão de nome e de commit.

## Estrutura

Organização **por domínio** (ADR-002, secao 2.1). Cada domínio em
`app/domains/<nome>/` contém as próprias camadas:

| Arquivo | Responsabilidade | Não faz |
|---|---|---|
| `router.py` | HTTP: recebe, valida, delega | Regra de negócio |
| `service.py` | Regra de negócio | Não conhece HTTP nem ORM |
| `repository.py` | Queries e agregações | Regra de negócio |
| `schemas.py` | Pydantic, separado por direção | — |
| `models.py` | Tabelas SQLAlchemy | — |

`app/domains/respondentes/` é o **domínio-exemplo completo** — use como molde.

## Setup local

No Windows:
```
.\venv\Scripts\activate
```

- No macOS/Linux:
```
source venv/bin/activate
```

pip install -e ".[dev]"
cp .env.example .env
pre-commit install --hook-type pre-commit --hook-type pre-push
```

O `--hook-type pre-push` instala a verificação do nome da branch
([cartilha](CONTRIBUTING.md)); sem ele, o erro só aparece no PR.

Subir o banco e aplicar migrations:

```bash
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

Docs da API: http://localhost:8000/api/v1/docs

## Qualidade

```bash
ruff check . && ruff format --check .
ruff format .
mypy app
pytest
```

## Migrations (ADR-002, secao 2.4)

```bash
alembic revision --autogenerate -m "descricao"   # SEMPRE revisar o resultado
alembic heads                                     # conferir antes de abrir PR
alembic upgrade head
```

**Regras que valem sempre:**

1. Autogenerate **nunca** vai para o repositório sem leitura linha a linha —
   renomear coluna vira drop+create e **perde dados**.
2. Migration passa por code review, com prioridade.
3. Conflito de heads: usar `alembic merge`, nunca editar `down_revision` à revelia.
4. No deploy: **Job dedicado**, nunca no startup do container.
5. Rollback: corrigir avançando com nova migration, não com `downgrade`.
6. Mudança destrutiva: dividir em passos (adicionar → migrar dados → remover).
