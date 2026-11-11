"""Wiring de injeção de dependência do domínio prismas."""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.prismas.repository import PrismaRepository
from app.domains.prismas.service import PrismaService


def get_repository(db: SessionDep) -> PrismaRepository:
    return PrismaRepository(db)


def get_service(
    repository: Annotated[PrismaRepository, Depends(get_repository)],
) -> PrismaService:
    return PrismaService(repository)


ServiceDep = Annotated[PrismaService, Depends(get_service)]
