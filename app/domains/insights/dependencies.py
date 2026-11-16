"""Wiring de injeção de dependência do domínio insights.

Só o `InsightService`, que a exclusão de membro (M-3) e o envio da resposta
(`responses`) usam. O domínio ainda não tem rota.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.insights.repository import InsightRepository
from app.domains.insights.service import InsightService
from app.domains.prismas.dependencies import ServiceDep as PrismaServiceDep


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
