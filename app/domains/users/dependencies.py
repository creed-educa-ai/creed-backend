"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.users.repository import UserRepository
from app.domains.users.service import UserService


def get_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRepository:
    return UserRepository(db)


def get_service(
    repository: Annotated[UserRepository, Depends(get_repository)],
) -> UserService:
    return UserService(repository)


ServiceDep = Annotated[UserService, Depends(get_service)]
