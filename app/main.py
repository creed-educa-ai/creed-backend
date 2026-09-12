"""Ponto de entrada da API do CREED.ai Educa.

Arquitetura registrada nos ADRs 001 (stack) e 002 (organização interna).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.domains.dashboards.router import router as dashboards_router
from app.domains.organizacoes.router import router as organizacoes_router
from app.domains.prismas.router import router as prismas_router
from app.domains.prognosticos.router import router as prognosticos_router
from app.domains.relatorios.router import router as relatorios_router
from app.domains.respondentes.router import router as respondentes_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ciclo de vida da aplicação.

    NOTA (ADR-002 secao 2.4.d; mecanismo revisto pelo ADR-0007): migrations
    NÃO rodam aqui. Schema é recurso compartilhado — migrar a partir do
    processo que serve requisição mistura duas responsabilidades que precisam
    falhar separado. A migration roda num passo dedicado do pipeline, num
    container descartável, antes de este container ser recriado.
    """
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    """Liveness/readiness probe para o Kubernetes."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}


for _router in (
    respondentes_router,
    organizacoes_router,
    prismas_router,
    dashboards_router,
    prognosticos_router,
    relatorios_router,
):
    app.include_router(_router, prefix=settings.API_V1_PREFIX)
