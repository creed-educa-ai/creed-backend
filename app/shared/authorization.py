"""Guarda de autenticação e nível de acesso"""

import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from app.domains.users.dependencies import ServiceDep as UserServiceDep
from app.domains.users.service import UserService
from app.external_services.keycloak.token import InvalidTokenError, validate_token

logger = logging.getLogger(__name__)


class AuthenticatedUser:
    """Identidade do usuário autenticado"""

    def __init__(self, sub: str, email: str | None, roles: list[str]) -> None:
        self.sub = sub
        self.email = email
        self.roles = roles

    def has_role(self, role: str) -> bool:
        return role in self.roles


def _extract_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    return header.removeprefix("Bearer ").strip()


async def _identity_from_token(request: Request) -> AuthenticatedUser:
    token = _extract_token(request)

    try:
        claims = await validate_token(token)
    except InvalidTokenError as exc:
        logger.info("Token rejeitado: %s", exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada"
        ) from exc

    return AuthenticatedUser(
        sub=claims["sub"],
        email=claims.get("email"),
        roles=claims.get("realm_access", {}).get("roles", []),
    )


async def _check_against_database(
    identity: AuthenticatedUser, users: UserService
) -> AuthenticatedUser:
    user = (
        await users.get_active_user_by_email(identity.email) if identity.email else None
    )

    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")

    if not identity.has_role(user.role.value):
        logger.error(
            "Divergência de cargo entre token (%s) e banco (%s) para o usuário %s",
            identity.roles,
            user.role.value,
            user.id,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada")

    return AuthenticatedUser(sub=str(user.id), email=user.email, roles=[user.role.value])


def require_role(*roles: str) -> Any:
    async def _dependency(
        identity: Annotated[AuthenticatedUser, Depends(_identity_from_token)],
        users: UserServiceDep,
    ) -> AuthenticatedUser:
        if not any(identity.has_role(role) for role in roles):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Cargo insuficiente para acessar"
            )

        return await _check_against_database(identity, users)

    return _dependency


async def current_user(
    identity: Annotated[AuthenticatedUser, Depends(_identity_from_token)],
    users: UserServiceDep,
) -> AuthenticatedUser:
    return await _check_against_database(identity, users)


CurrentUserDep = Annotated[AuthenticatedUser, Depends(current_user)]
