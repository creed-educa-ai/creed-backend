"""Wiring de injeção de dependência do domínio participants.

Monta a cadeia sessão -> repository -> service, mantendo o router livre de
construção de objetos. O service recebe também o `DocumentService`, pela mesma
injeção que `authentication` usa para o `UserService`.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.documents.dependencies import ServiceDep as DocumentServiceDep
from app.domains.participants.repository import ParticipantRepository
from app.domains.participants.service import ParticipantService


def get_repository(
    db: SessionDep,
) -> ParticipantRepository:
    return ParticipantRepository(db)


def get_service(
    repository: Annotated[ParticipantRepository, Depends(get_repository)],
    documents: DocumentServiceDep,
) -> ParticipantService:
    return ParticipantService(repository, documents)


ServiceDep = Annotated[ParticipantService, Depends(get_service)]
