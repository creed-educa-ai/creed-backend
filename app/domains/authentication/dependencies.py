"""Injeção de dependência do domínio"""

from typing import Annotated

from fastapi import Depends

from app.domains.authentication.service import AuthenticationService
from app.domains.links.dependencies import ServiceDep as LinkServiceDep
from app.domains.users.dependencies import ServiceDep as UserServiceDep


def get_service(users: UserServiceDep, links: LinkServiceDep) -> AuthenticationService:
    return AuthenticationService(users, links)


ServiceDep = Annotated[AuthenticationService, Depends(get_service)]
