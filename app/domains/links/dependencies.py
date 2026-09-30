"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.links.repository import LinkRepository
from app.domains.links.service import LinkService


def get_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LinkRepository:
    return LinkRepository(db)


def get_service(
    repository: Annotated[LinkRepository, Depends(get_repository)],
) -> LinkService:
    return LinkService(repository)


ServiceDep = Annotated[LinkService, Depends(get_service)]
