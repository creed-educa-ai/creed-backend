"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.department.dependencies import ServiceDep as DepartmentServiceDep
from app.domains.links.repository import LinkRepository
from app.domains.links.service import LinkService
from app.domains.organizacoes.dependencies import (
    ServiceDep as OrganizationServiceDep,
)
from app.domains.participants.dependencies import ServiceDep as ParticipantServiceDep


def get_repository(
    db: SessionDep,
) -> LinkRepository:
    return LinkRepository(db)


def get_service(
    repository: Annotated[LinkRepository, Depends(get_repository)],
    participants: ParticipantServiceDep,
    organizations: OrganizationServiceDep,
    departments: DepartmentServiceDep,
) -> LinkService:
    return LinkService(repository, participants, organizations, departments)


ServiceDep = Annotated[LinkService, Depends(get_service)]
