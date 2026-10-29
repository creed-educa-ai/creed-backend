"""Wiring de injeção de dependência do domínio (ADR-002, secao 2.3).

Usa o sistema Depends nativo do FastAPI para montar a cadeia
repository -> service, mantendo o router livre de construção de objetos.
"""

from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.domains.links.dependencies import ServiceDep as LinkServiceDep
from app.domains.organizacoes.dependencies import (
    ServiceDep as OrganizationServiceDep,
)
from app.domains.participants.dependencies import (
    ServiceDep as ParticipantServiceDep,
)
from app.domains.users.repository import UserRepository
from app.domains.users.service import MemberService, UserService


def get_repository(
    db: SessionDep,
) -> UserRepository:
    return UserRepository(db)


def get_service(
    repository: Annotated[UserRepository, Depends(get_repository)],
    links: LinkServiceDep,
) -> UserService:
    return UserService(repository, links)


ServiceDep = Annotated[UserService, Depends(get_service)]


def get_member_service(
    users: Annotated[UserService, Depends(get_service)],
    participants: ParticipantServiceDep,
    links: LinkServiceDep,
    organizations: OrganizationServiceDep,
) -> MemberService:
    return MemberService(users, participants, links, organizations)


MemberServiceDep = Annotated[MemberService, Depends(get_member_service)]
