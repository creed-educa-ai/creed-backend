"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.vinculos.repository import VinculoRepository
from app.domains.vinculos.service import VinculoService


def get_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VinculoRepository:
    return VinculoRepository(db)


def get_service(
    repository: Annotated[VinculoRepository, Depends(get_repository)],
) -> VinculoService:
    return VinculoService(repository)


ServiceDep = Annotated[VinculoService, Depends(get_service)]
