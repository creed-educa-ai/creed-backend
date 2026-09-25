"""Ponto de entrada da API do CREED.ai Educa.

Arquitetura registrada nos ADRs 001 (stack) e 002 (organização interna).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.domains.authentication.router import router as authentication_router
from app.domains.dashboards.router import router as dashboards_router
from app.domains.organizacoes.router import router as organizacoes_router
from app.domains.prismas.router import router as prismas_router
from app.domains.prognosticos.router import router as prognosticos_router
from app.domains.relatorios.router import router as relatorios_router
from app.domains.responses.router import router as respostas_router
from app.domains.users.router import router as user_router
from app.shared.schemas import HealthResponse

API_DESCRIPTION = """
API do CREED.ai Educa para autenticação, gestão de usuários e aplicação dos
formulários de Plasticidade Humana e Inteligência Neuroinovadora.

As rotas versionadas usam o prefixo `/api/v1`. Para acessar uma rota protegida,
obtenha o `access_token` em **authentication > Iniciar sessão** e informe-o no botão
**Authorize** como token Bearer.
"""

OPENAPI_TAGS = [
    {
        "name": "infra",
        "description": "Verificação operacional da disponibilidade da API.",
    },
    {
        "name": "authentication",
        "description": "Início, renovação e consulta da sessão autenticada.",
    },
    {
        "name": "users",
        "description": "Criação e remoção dos usuários da plataforma.",
    },
    {
        "name": "form-responses",
        "description": "Abertura e submissão de respostas de formulário.",
    },
]


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
    description=API_DESCRIPTION,
    version="0.1.0",
    openapi_tags=OPENAPI_TAGS,
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


@app.get(
    "/health",
    tags=["infra"],
    response_model=HealthResponse,
    summary="Consultar a saúde da API",
    description=(
        "Confirma que o processo está disponível e informa o ambiente atual. "
        "Não exige autenticação."
    ),
    response_description="API disponível e ambiente identificado.",
    operation_id="get_health",
)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.ENVIRONMENT)


for _router in (
    authentication_router,
    respostas_router,
    organizacoes_router,
    prismas_router,
    dashboards_router,
    prognosticos_router,
    relatorios_router,
    user_router,
):
    app.include_router(_router, prefix=settings.API_V1_PREFIX)
