"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.links.repository import LinkRepository
from app.domains.links.service import LinkService


def get_repository(
    db: SessionDep,
) -> LinkRepository:
    return LinkRepository(db)


def get_service(
    repository: Annotated[LinkRepository, Depends(get_repository)],
) -> LinkService:
    return LinkService(repository)


ServiceDep = Annotated[LinkService, Depends(get_service)]
