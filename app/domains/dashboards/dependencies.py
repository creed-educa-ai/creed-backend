"""Wiring de injeção de dependência do domínio dashboards.

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.dashboards.repository import DashboardRepository
from app.domains.dashboards.service import DashboardService
from app.domains.prismas.dependencies import ServiceDep as PrismaServiceDep


def get_repository(db: SessionDep) -> DashboardRepository:
    return DashboardRepository(db)


def get_service(
    repository: Annotated[DashboardRepository, Depends(get_repository)],
    prismas_service: PrismaServiceDep,
) -> DashboardService:
    return DashboardService(repository, prismas_service)


ServiceDep = Annotated[DashboardService, Depends(get_service)]
