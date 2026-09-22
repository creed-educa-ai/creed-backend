"""Wiring de injeção de dependência do domínio form_responses.

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.responses.repository import FormResponseRepository
from app.domains.responses.service import FormResponseService


def get_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FormResponseRepository:
    return FormResponseRepository(db)


def get_service(
    repository: Annotated[FormResponseRepository, Depends(get_repository)],
) -> FormResponseService:
    return FormResponseService(repository)


ServiceDep = Annotated[FormResponseService, Depends(get_service)]
