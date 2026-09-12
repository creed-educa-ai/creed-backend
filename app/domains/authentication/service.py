"""Regra de negócio do domínio authentication"""

from typing import Any

from app.domains.authentication.schemas import (
    LoginRequest,
    SessionResponse,
    UserSessionResponse,
)
from app.domains.users.service import UserService
from app.external_services.keycloak import client as keycloak_client
from app.external_services.keycloak.token import validate_token
from app.shared.exceptions import AuthenticationError

_INVALID_CREDENTIALS = "E-mail ou senha inválidos"
_SESSION_EXPIRED = "Sessão expirada, faça login novamente"


class AuthenticationService:
    def __init__(self, users: UserService) -> None:
        self.users = users

    async def login(self, data: LoginRequest) -> SessionResponse:
        try:
            tokens = await keycloak_client.login(data.email, data.password)
        except keycloak_client.InvalidCredentialsError as exc:
            raise AuthenticationError(_INVALID_CREDENTIALS) from exc
        except keycloak_client.KeycloakUnavailableError as exc:
            raise AuthenticationError("Não foi possível autenticar agora") from exc

        return await self._build_session(tokens, error_message=_INVALID_CREDENTIALS)

    async def refresh(self, refresh_token: str) -> SessionResponse:
        try:
            tokens = await keycloak_client.refresh(refresh_token)
        except keycloak_client.InvalidCredentialsError as exc:
            raise AuthenticationError(_SESSION_EXPIRED) from exc
        except keycloak_client.KeycloakUnavailableError as exc:
            raise AuthenticationError("Não foi possível renovar a sessão agora") from exc

        return await self._build_session(tokens, error_message=_SESSION_EXPIRED)

    async def _build_session(
        self, tokens: dict[str, Any], error_message: str
    ) -> SessionResponse:
        claims = await validate_token(tokens["access_token"])
        email = claims.get("email")

        user = await self.users.get_active_user_by_email(email) if email else None
        if user is None:
            raise AuthenticationError(error_message)

        return SessionResponse(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_in=tokens["expires_in"],
            user=UserSessionResponse(
                id=str(user.id),
                email=user.email,
                role=user.role.value,
            ),
        )
