"""Guarda de autenticação e nível de acesso"""

import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.domains.users.dependencies import ServiceDep as UserServiceDep
from app.domains.users.service import UserService
from app.external_services.keycloak.token import (
    InvalidTokenError,
    JwksUnavailableError,
    validate_token,
)

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(
    bearerFormat="JWT",
    scheme_name="BearerAuth",
    description=("Token JWT retornado pelos endpoints de login ou renovação de sessão."),
    auto_error=False,
)


class AuthenticatedUser:
    """Identidade do usuário autenticado.

    `link_id` e `organization_id` nascem `None`: quem monta a partir só do
    token (`_identity_from_token`) não os tem. Só `_check_against_database`,
    que já consultou o vínculo, os preenche.
    """

    def __init__(
        self,
        sub: str,
        email: str | None,
        roles: list[str],
        link_id: str | None = None,
        organization_id: str | None = None,
    ) -> None:
        self.sub = sub
        self.email = email
        self.roles = roles
        self.link_id = link_id
        self.organization_id = organization_id

    def has_role(self, role: str) -> bool:
        return role in self.roles


def _extract_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    return credentials.credentials.strip()


async def _identity_from_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    token = _extract_token(credentials)

    try:
        claims = await validate_token(token)
    except (InvalidTokenError, JwksUnavailableError) as exc:
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
    # `None` cobre usuário inexistente, inativo, sem vínculo, ou vínculo que o
    # LinkService não encontra — a guarda trata os quatro como "sem acesso"
    # (P-008), sem distinguir. O papel comparado é o do vínculo, não mais o de
    # `user.role`: a coluna deixou de ser lida (CREED-32).
    access = (
        await users.get_active_user_access_by_email(identity.email)
        if identity.email
        else None
    )

    if access is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")

    if not identity.has_role(access.role):
        logger.error(
            "Divergência de cargo entre token (%s) e vínculo (%s) para o usuário %s",
            identity.roles,
            access.role,
            access.id,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada")

    return AuthenticatedUser(
        sub=str(access.id),
        email=access.email,
        roles=[access.role],
        link_id=str(access.link_id),
        organization_id=str(access.organization_id),
    )


def require_role(*roles: str) -> Any:
    async def _dependency(
        identity: Annotated[AuthenticatedUser, Depends(_identity_from_token)],
        users: UserServiceDep,
    ) -> AuthenticatedUser:
        if not any(identity.has_role(role) for role in roles):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Cargo insuficiente para acessar"
            )

        user = await _check_against_database(identity, users)

        # O token pode trazer mais de um papel (`admin` e `gestor`, por exemplo), e
        # `_check_against_database` só confere se o papel do vínculo está entre
        # eles. Quem decide a rota é o vínculo (CREED-32), então a conferência se
        # repete sobre o usuário já verificado no banco.
        if not any(user.has_role(role) for role in roles):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Cargo insuficiente para acessar"
            )

        return user

    return _dependency


async def current_user(
    identity: Annotated[AuthenticatedUser, Depends(_identity_from_token)],
    users: UserServiceDep,
) -> AuthenticatedUser:
    return await _check_against_database(identity, users)


CurrentUserDep = Annotated[AuthenticatedUser, Depends(current_user)]
