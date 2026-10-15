"""Wiring de injeção de dependência do domínio organizacoes.

Monta a cadeia sessão -> repository -> service, mantendo o router livre de
construção de objetos. O service recebe também o `DocumentService`, pela mesma
injeção que `participants` usa.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.documents.dependencies import ServiceDep as DocumentServiceDep
from app.domains.organizacoes.repository import OrganizationRepository
from app.domains.organizacoes.service import OrganizationService


def get_repository(db: SessionDep) -> OrganizationRepository:
    return OrganizationRepository(db)


def get_service(
    repository: Annotated[OrganizationRepository, Depends(get_repository)],
    documents: DocumentServiceDep,
) -> OrganizationService:
    return OrganizationService(repository, documents)


ServiceDep = Annotated[OrganizationService, Depends(get_service)]
