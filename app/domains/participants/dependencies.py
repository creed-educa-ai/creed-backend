"""Wiring de injeção de dependência do domínio participants.

Monta a cadeia sessão -> repository -> service, mantendo o router livre de
construção de objetos.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.participants.repository import ParticipantRepository
from app.domains.participants.service import ParticipantService


def get_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ParticipantRepository:
    return ParticipantRepository(db)


def get_service(
    repository: Annotated[ParticipantRepository, Depends(get_repository)],
) -> ParticipantService:
    return ParticipantService(repository)


ServiceDep = Annotated[ParticipantService, Depends(get_service)]
