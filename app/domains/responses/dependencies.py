"""Wiring de injeção de dependência do domínio form_responses.

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.forms.dependencies import ServiceDep as FormServiceDep
from app.domains.questions.dependencies import ServiceDep as QuestionServiceDep
from app.domains.responses.repository import AnswerRepository, FormResponseRepository
from app.domains.responses.service import AnswerService, FormResponseService


def get_repository(
    db: SessionDep,
) -> FormResponseRepository:
    return FormResponseRepository(db)


def get_service(
    repository: Annotated[FormResponseRepository, Depends(get_repository)],
    forms: FormServiceDep,
) -> FormResponseService:
    return FormResponseService(repository, forms)


ServiceDep = Annotated[FormResponseService, Depends(get_service)]


def get_answer_repository(
    db: SessionDep,
) -> AnswerRepository:
    return AnswerRepository(db)


def get_answer_service(
    answers: Annotated[AnswerRepository, Depends(get_answer_repository)],
    form_responses: Annotated[FormResponseRepository, Depends(get_repository)],
    questions: QuestionServiceDep,
) -> AnswerService:
    return AnswerService(answers, form_responses, questions)


AnswerServiceDep = Annotated[AnswerService, Depends(get_answer_service)]
