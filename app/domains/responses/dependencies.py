"""Wiring de injeção de dependência do domínio form_responses.

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.responses.repository import AnswerRepository, FormResponseRepository
from app.domains.responses.service import AnswerService, FormResponseService


def get_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FormResponseRepository:
    return FormResponseRepository(db)


def get_service(
    repository: Annotated[FormResponseRepository, Depends(get_repository)],
) -> FormResponseService:
    return FormResponseService(repository)


ServiceDep = Annotated[FormResponseService, Depends(get_service)]


def get_answer_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnswerRepository:
    return AnswerRepository(db)


def get_answer_service(
    repository: Annotated[AnswerRepository, Depends(get_answer_repository)],
) -> AnswerService:
    return AnswerService(repository)


AnswerServiceDep = Annotated[AnswerService, Depends(get_answer_service)]
