"""Wiring de injeção de dependência do domínio documents.

Monta a cadeia sessão -> repository -> service. Outro domínio que precise de
documento recebe o `ServiceDep` daqui, nunca o model.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.documents.repository import DocumentRepository
from app.domains.documents.service import DocumentService


def get_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentRepository:
    return DocumentRepository(db)


def get_service(
    repository: Annotated[DocumentRepository, Depends(get_repository)],
) -> DocumentService:
    return DocumentService(repository)


ServiceDep = Annotated[DocumentService, Depends(get_service)]
