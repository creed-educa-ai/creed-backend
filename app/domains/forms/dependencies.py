"""Wiring de injeção de dependência do domínio  .

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.forms.repository import FormRepository
from app.domains.forms.service import FormService
from app.domains.organizacoes.dependencies import (
    ServiceDep as OrganizationServiceDep,
)


def get_repository(
    db: SessionDep,
) -> FormRepository:
    return FormRepository(db)


def get_service(
    repository: Annotated[FormRepository, Depends(get_repository)],
    organizations: OrganizationServiceDep,
) -> FormService:
    return FormService(repository, organizations)


ServiceDep = Annotated[FormService, Depends(get_service)]
