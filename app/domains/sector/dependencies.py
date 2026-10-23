"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.sector.repository import SectorRepository
from app.domains.sector.service import SectorService


def get_repository(
    db: SessionDep,
) -> SectorRepository:
    return SectorRepository(db)


def get_service(
    repository: Annotated[SectorRepository, Depends(get_repository)],
) -> SectorService:
    return SectorService(repository)


ServiceDep = Annotated[SectorService, Depends(get_service)]
