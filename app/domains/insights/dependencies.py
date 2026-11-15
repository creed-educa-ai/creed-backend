"""Wiring de injeção de dependência do domínio insights.

O `InsightService` da requisição, que a exclusão de membro (M-3) e o envio da
resposta (`responses`) usam, e o do worker da esteira, que não passa pelo `Depends`
porque não atende requisição. O domínio ainda não tem rota.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionDep
from app.domains.insights.repository import InsightRepository
from app.domains.insights.service import InsightService
from app.domains.prismas.dependencies import ServiceDep as PrismaServiceDep
from app.domains.prismas.dependencies import get_repository as get_prisma_repository
from app.domains.prismas.dependencies import get_service as get_prisma_service
from app.external_services.n8n.client import N8NClient


def get_repository(
    db: SessionDep,
) -> InsightRepository:
    return InsightRepository(db)


def get_service(
    repository: Annotated[InsightRepository, Depends(get_repository)],
    prismas: PrismaServiceDep,
) -> InsightService:
    return InsightService(repository, prismas)


ServiceDep = Annotated[InsightService, Depends(get_service)]


def build_dispatch_service(session: AsyncSession, n8n: N8NClient) -> InsightService:
    """O service do worker (CREED-804): a mesma montagem, com a sessão da unidade de
    trabalho que o worker abriu e o client do N8N que ele mantém aberto."""
    prismas = get_prisma_service(get_prisma_repository(session))
    return InsightService(get_repository(session), prismas, n8n)
