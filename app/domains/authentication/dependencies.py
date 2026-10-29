"""Injeção de dependência do domínio"""

from typing import Annotated

from fastapi import Depends

from app.domains.authentication.service import AuthenticationService
from app.domains.users.dependencies import ServiceDep as UserServiceDep


def get_service(users: UserServiceDep) -> AuthenticationService:
    return AuthenticationService(users)


ServiceDep = Annotated[AuthenticationService, Depends(get_service)]
