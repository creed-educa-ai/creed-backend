"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.questions.repository import QuestionRepository
from app.domains.questions.service import QuestionService


def get_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuestionRepository:
    return QuestionRepository(db)


def get_service(
    repository: Annotated[QuestionRepository, Depends(get_repository)],
) -> QuestionService:
    return QuestionService(repository)


ServiceDep = Annotated[QuestionService, Depends(get_service)]
