"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.forms.dependencies import ServiceDep as FormServiceDep
from app.domains.questions.repository import (
    QuestionOptionRepository,
    QuestionOptionTranslationRepository,
    QuestionRepository,
    QuestionTranslationRepository,
)
from app.domains.questions.service import (
    QuestionOptionService,
    QuestionOptionTranslationService,
    QuestionService,
    QuestionTranslationService,
)


def get_repository(
    db: SessionDep,
) -> QuestionRepository:
    return QuestionRepository(db)


def get_service(
    repository: Annotated[QuestionRepository, Depends(get_repository)],
    forms: FormServiceDep,
) -> QuestionService:
    return QuestionService(repository, forms)


ServiceDep = Annotated[QuestionService, Depends(get_service)]


def get_translation_repository(
    db: SessionDep,
) -> QuestionTranslationRepository:
    return QuestionTranslationRepository(db)


def get_translation_service(
    repository: Annotated[
        QuestionTranslationRepository, Depends(get_translation_repository)
    ],
    questions: Annotated[QuestionService, Depends(get_service)],
) -> QuestionTranslationService:
    return QuestionTranslationService(repository, questions)


QuestionTranslationServiceDep = Annotated[
    QuestionTranslationService, Depends(get_translation_service)
]


def get_option_repository(
    db: SessionDep,
) -> QuestionOptionRepository:
    return QuestionOptionRepository(db)


def get_option_service(
    repository: Annotated[QuestionOptionRepository, Depends(get_option_repository)],
    questions: Annotated[QuestionService, Depends(get_service)],
) -> QuestionOptionService:
    return QuestionOptionService(repository, questions)


OptionServiceDep = Annotated[QuestionOptionService, Depends(get_option_service)]


def get_option_translation_repository(
    db: SessionDep,
) -> QuestionOptionTranslationRepository:
    return QuestionOptionTranslationRepository(db)


def get_option_translation_service(
    repository: Annotated[
        QuestionOptionTranslationRepository,
        Depends(get_option_translation_repository),
    ],
    options: Annotated[QuestionOptionService, Depends(get_option_service)],
) -> QuestionOptionTranslationService:
    return QuestionOptionTranslationService(repository, options)


QuestionOptionTranslationServiceDep = Annotated[
    QuestionOptionTranslationService, Depends(get_option_translation_service)
]
