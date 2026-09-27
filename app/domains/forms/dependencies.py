"""Wiring de injeção de dependência do domínio  .

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.forms.repository import FormRepository
from app.domains.forms.service import FormService


def get_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FormRepository:
    return FormRepository(db)


def get_service(
    repository: Annotated[FormRepository, Depends(get_repository)],
) -> FormService:
    return FormService(repository)


ServiceDep = Annotated[FormService, Depends(get_service)]
